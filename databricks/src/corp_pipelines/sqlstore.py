"""The pipeline's only SQL access: read ledger reference data (and, once, the seeded history
for the backfill), write serving and ops.pipeline_*.

Connects as the `pipeline_writer` principal (db/rls.sql exempts that role from row-level
security by membership, so one connection can refresh every company).

  SqlAlchemyStore  local compose and tests: SERVING_DB_URL (SQL Server or SQLite)
  JdbcStore        Databricks: the runtime's SQL Server JDBC driver with an Entra access
                   token for the job identity (no passwords)

Both implement the same methods; every write method is one transaction.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Iterable

TRACE_SQL_EXISTING = "SELECT payment_id FROM ops.pipeline_trace WHERE stage = ? AND payment_id BETWEEN ? AND ?"
CASH_COLUMNS = (
    "company_id", "as_of_date", "total_cash", "available", "scheduled_out_7d",
    "payroll_due_date", "payroll_due_amount", "forecast_low", "refreshed_at",
)
RUN_COLUMNS = (
    "run_id", "started_at", "finished_at", "events_ingested", "events_new",
    "companies_refreshed", "status", "next_batch_at",
)
FORECAST_COLUMNS = (
    "company_id", "forecast_date", "predicted_balance", "lower_bound", "upper_bound",
    "model_name", "model_version", "generated_at",
)
ANOMALY_COLUMNS = (
    "id", "company_id", "payment_id", "transaction_id", "occurred_at", "counterparty", "amount",
    "score", "reason", "detected_at", "model_name", "model_version",
)
MODEL_COLUMNS = ("model_name", "registered_name", "model_version", "trained_at", "metrics", "run_id")
PAYMENT_COLUMNS = (
    "id", "company_id", "from_account_id", "to_account_id", "beneficiary_id", "beneficiary_name", "amount",
    "currency", "value_date", "reference", "status", "created_by", "created_at", "decided_by", "decided_at",
    "executed_at",
)
TRANSACTION_COLUMNS = (
    "id", "company_id", "account_id", "payment_id", "booked_at", "value_date", "amount", "balance_after",
    "category", "counterparty", "description",
)
# The backfill takes ledger rows that never went through the outbox: the seeded history.
# Rows a portal action already published reach the lake as their own events.
BACKFILL_PAYMENTS_SQL = """
SELECT p.id, p.company_id, p.from_account_id, p.to_account_id, p.beneficiary_id, b.name,
       p.amount, p.currency, CONVERT(CHAR(10), p.value_date, 23), p.reference, p.status,
       p.created_by, CONVERT(VARCHAR(30), p.created_at, 126), p.decided_by,
       CONVERT(VARCHAR(30), p.decided_at, 126), CONVERT(VARCHAR(30), p.executed_at, 126)
FROM ops.payments p LEFT JOIN ops.beneficiaries b ON b.id = p.beneficiary_id
WHERE p.status = 'EXECUTED' AND NOT EXISTS (
    SELECT 1 FROM ops.outbox o WHERE o.aggregate_type = 'payment' AND o.aggregate_id = CAST(p.id AS NVARCHAR(40)))
ORDER BY p.id"""
BACKFILL_TRANSACTIONS_SQL = """
SELECT t.id, t.company_id, t.account_id, t.payment_id, CONVERT(VARCHAR(30), t.booked_at, 126),
       CONVERT(CHAR(10), t.value_date, 23), t.amount, t.balance_after, t.category, t.counterparty, t.description
FROM ops.transactions t
WHERE NOT EXISTS (
    SELECT 1 FROM ops.outbox o WHERE o.aggregate_type = 'transaction' AND o.aggregate_id = CAST(t.id AS NVARCHAR(40)))
ORDER BY t.id"""


class SqlAlchemyStore:
    def __init__(self, engine_or_url):
        from sqlalchemy import (
            BigInteger, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text, create_engine,
        )

        if isinstance(engine_or_url, str):
            kw = {"pool_pre_ping": True}
            if engine_or_url.startswith("mssql+pyodbc"):
                kw["fast_executemany"] = True
            self.engine = create_engine(engine_or_url, **kw)
        else:
            self.engine = engine_or_url
        money = Numeric(18, 2, asdecimal=True)
        md = MetaData()
        self.accounts = Table(
            "accounts", md, Column("id", Integer), Column("company_id", Integer),
            Column("kind", String(20)), Column("balance", money), schema="ops",
        )
        self.scheduled = Table(
            "scheduled_payments", md, Column("company_id", Integer), Column("kind", String(20)),
            Column("amount", money), Column("due_date", Date), schema="ops",
        )
        self.cash = Table(
            "cash_position", md, Column("company_id", Integer), Column("as_of_date", Date),
            Column("total_cash", money), Column("available", money), Column("scheduled_out_7d", money),
            Column("payroll_due_date", Date), Column("payroll_due_amount", money),
            Column("forecast_low", money), Column("refreshed_at", DateTime), schema="serving",
        )
        self.trace = Table(
            "pipeline_trace", md, Column("payment_id", BigInteger), Column("stage", String(20)),
            Column("at", DateTime), schema="ops",
        )
        self.runs = Table(
            "pipeline_runs", md, Column("id", BigInteger, primary_key=True), Column("run_id", String(64)),
            Column("started_at", DateTime), Column("finished_at", DateTime), Column("events_ingested", Integer),
            Column("events_new", Integer), Column("companies_refreshed", Integer), Column("status", String(20)),
            Column("next_batch_at", DateTime), schema="ops",
        )
        self.payments = Table(
            "payments", md, Column("id", BigInteger), Column("company_id", Integer), Column("from_account_id", Integer),
            Column("to_account_id", Integer), Column("beneficiary_id", Integer), Column("amount", money),
            Column("currency", String(3)), Column("value_date", Date), Column("reference", String(140)),
            Column("status", String(20)), Column("created_by", Integer), Column("created_at", DateTime),
            Column("decided_by", Integer), Column("decided_at", DateTime), Column("executed_at", DateTime), schema="ops",
        )
        self.beneficiaries = Table(
            "beneficiaries", md, Column("id", Integer), Column("name", String(200)), schema="ops",
        )
        self.transactions = Table(
            "transactions", md, Column("id", BigInteger), Column("company_id", Integer), Column("account_id", Integer),
            Column("payment_id", BigInteger), Column("booked_at", DateTime), Column("value_date", Date),
            Column("amount", money), Column("balance_after", money), Column("category", String(30)),
            Column("counterparty", String(200)), Column("description", String(200)), schema="ops",
        )
        self.outbox = Table(
            "outbox", md, Column("aggregate_type", String(40)), Column("aggregate_id", String(40)), schema="ops",
        )
        self.forecast = Table(
            "forecast", md, Column("company_id", Integer), Column("forecast_date", Date),
            Column("predicted_balance", money), Column("lower_bound", money), Column("upper_bound", money),
            Column("model_name", String(100)), Column("model_version", String(40)), Column("generated_at", DateTime),
            schema="serving",
        )
        self.anomalies = Table(
            "anomalies", md, Column("id", Integer), Column("company_id", Integer), Column("payment_id", BigInteger),
            Column("transaction_id", BigInteger), Column("occurred_at", DateTime), Column("counterparty", String(200)),
            Column("amount", money), Column("score", Numeric(6, 4, asdecimal=True)), Column("reason", String(400)),
            Column("detected_at", DateTime), Column("model_name", String(100)), Column("model_version", String(40)),
            schema="serving",
        )
        self.models = Table(
            "models", md, Column("model_name", String(100)), Column("registered_name", String(200)),
            Column("model_version", String(40)), Column("trained_at", DateTime), Column("metrics", Text),
            Column("run_id", String(64)), schema="serving",
        )

    # ---------------------------------------------------------------- reads

    def read_accounts(self) -> list[tuple[int, int, str, Decimal]]:
        from sqlalchemy import select

        a = self.accounts
        with self.engine.connect() as conn:
            rows = conn.execute(select(a.c.id, a.c.company_id, a.c.kind, a.c.balance).order_by(a.c.id)).all()
        return [(int(r[0]), int(r[1]), r[2], Decimal(str(r[3]))) for r in rows]

    def read_scheduled(self) -> list[tuple[int, str, Decimal, date]]:
        from sqlalchemy import select

        s = self.scheduled
        with self.engine.connect() as conn:
            rows = conn.execute(select(s.c.company_id, s.c.kind, s.c.amount, s.c.due_date)).all()
        return [(int(r[0]), r[1], Decimal(str(r[2])), r[3]) for r in rows]

    def read_backfill_payments(self) -> list[dict]:
        from sqlalchemy import String, and_, cast, exists, select

        p, b, o = self.payments, self.beneficiaries, self.outbox
        published = exists().where(and_(o.c.aggregate_type == "payment", o.c.aggregate_id == cast(p.c.id, String(40))))
        q = (
            select(p, b.c.name.label("beneficiary_name"))
            .select_from(p.outerjoin(b, b.c.id == p.c.beneficiary_id))
            .where(and_(p.c.status == "EXECUTED", ~published))
            .order_by(p.c.id)
        )
        with self.engine.connect() as conn:
            return [{k: r[k] for k in PAYMENT_COLUMNS} for r in conn.execute(q).mappings()]

    def read_backfill_transactions(self) -> list[dict]:
        from sqlalchemy import String, and_, cast, exists, select

        tx, o = self.transactions, self.outbox
        published = exists().where(and_(o.c.aggregate_type == "transaction", o.c.aggregate_id == cast(tx.c.id, String(40))))
        with self.engine.connect() as conn:
            rows = conn.execute(select(tx).where(~published).order_by(tx.c.id)).mappings()
            return [{k: r[k] for k in TRANSACTION_COLUMNS} for r in rows]

    def read_scoring_state(self) -> dict:
        """What serving currently holds: {(model_name, model_version, first forecast_date)} and
        {(model_name, model_version)} of the anomalies."""
        from sqlalchemy import func, select

        f, a = self.forecast, self.anomalies
        with self.engine.connect() as conn:
            fc = conn.execute(select(f.c.model_name, f.c.model_version, func.min(f.c.forecast_date))
                              .group_by(f.c.model_name, f.c.model_version)).all()
            an = conn.execute(select(a.c.model_name, a.c.model_version).distinct()).all()
        return {"forecast": {(r[0], r[1], _as_date(r[2])) for r in fc}, "anomalies": {(r[0], r[1]) for r in an}}

    # ---------------------------------------------------------------- writes

    def write_trace(self, payment_ids: Iterable[int], stage: str, at: datetime) -> None:
        from sqlalchemy import and_, select

        ids = sorted({int(p) for p in payment_ids})
        if not ids:
            return
        tr = self.trace
        with self.engine.begin() as conn:
            seen = set(conn.execute(
                select(tr.c.payment_id).where(and_(tr.c.stage == stage, tr.c.payment_id.in_(ids)))
            ).scalars())
            rows = [{"payment_id": p, "stage": stage, "at": at} for p in ids if p not in seen]
            if rows:
                conn.execute(tr.insert(), rows)

    def replace_cash_positions(self, rows: list[dict]) -> None:
        """Replace each (company, as_of_date) row in serving.cash_position, all in one transaction."""
        from sqlalchemy import and_, delete

        c = self.cash
        with self.engine.begin() as conn:
            for r in rows:
                conn.execute(delete(c).where(and_(c.c.company_id == r["company_id"], c.c.as_of_date == r["as_of_date"])))
            if rows:
                conn.execute(c.insert(), [{k: r[k] for k in CASH_COLUMNS} for r in rows])

    def write_run(self, run: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(self.runs.insert().values(**{k: run[k] for k in RUN_COLUMNS}))

    def replace_scores(self, forecast: list[dict], anomalies: list[dict]) -> None:
        """Replace serving.forecast and serving.anomalies with one scoring run's rows, atomically."""
        from sqlalchemy import delete

        with self.engine.begin() as conn:
            conn.execute(delete(self.forecast))
            conn.execute(delete(self.anomalies))
            if forecast:
                conn.execute(self.forecast.insert(), [{k: r[k] for k in FORECAST_COLUMNS} for r in forecast])
            if anomalies:
                conn.execute(self.anomalies.insert(), [{k: r[k] for k in ANOMALY_COLUMNS} for r in anomalies])

    def write_models(self, rows: list[dict]) -> None:
        from sqlalchemy import delete

        m = self.models
        with self.engine.begin() as conn:
            for r in rows:
                conn.execute(delete(m).where(m.c.model_name == r["model_name"]))
            if rows:
                conn.execute(m.insert(), [{k: r[k] for k in MODEL_COLUMNS} for r in rows])


def _as_date(v):
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _ts(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(v.toPlainString())


class JdbcStore:
    """SQL Server JDBC through the Spark driver's JVM (py4j), authenticated by access token."""

    def __init__(self, spark, server: str, database: str, token: Callable[[], str]):
        self.jvm = spark.sparkContext._jvm
        self.url = (
            f"jdbc:sqlserver://{server}:1433;database={database};encrypt=true;"
            "trustServerCertificate=false;hostNameInCertificate=*.database.windows.net;loginTimeout=30;"
        )
        self.token = token

    def _connect(self):
        props = self.jvm.java.util.Properties()
        props.setProperty("accessToken", self.token())
        conn = self.jvm.java.sql.DriverManager.getConnection(self.url, props)
        conn.setAutoCommit(False)
        return conn

    def _bind(self, ps, values) -> None:
        for i, v in enumerate(values, start=1):
            if v is None:
                ps.setNull(i, self.jvm.java.sql.Types.NULL)
            elif isinstance(v, datetime):
                ps.setTimestamp(i, self.jvm.java.sql.Timestamp.valueOf(v.strftime("%Y-%m-%d %H:%M:%S.%f")))
            elif isinstance(v, date):
                ps.setDate(i, self.jvm.java.sql.Date.valueOf(v.isoformat()))
            elif isinstance(v, Decimal):
                ps.setBigDecimal(i, self.jvm.java.math.BigDecimal(str(v)))
            elif isinstance(v, int):
                ps.setLong(i, v)
            else:
                ps.setString(i, str(v))

    def _transaction(self, statements: list[tuple[str, list[tuple]]]) -> None:
        conn = self._connect()
        try:
            for sql, param_rows in statements:
                ps = conn.prepareStatement(sql)
                for params in param_rows:
                    self._bind(ps, params)
                    ps.addBatch()
                ps.executeBatch()
                ps.close()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _query(self, sql: str, params: tuple, read: Callable) -> list:
        conn = self._connect()
        try:
            ps = conn.prepareStatement(sql)
            self._bind(ps, params)
            rs = ps.executeQuery()
            out = []
            while rs.next():
                out.append(read(rs))
            return out
        finally:
            conn.close()

    def read_accounts(self):
        return self._query(
            "SELECT id, company_id, kind, balance FROM ops.accounts ORDER BY id", (),
            lambda rs: (rs.getInt(1), rs.getInt(2), rs.getString(3), Decimal(rs.getBigDecimal(4).toPlainString())),
        )

    def read_scheduled(self):
        return self._query(
            "SELECT company_id, kind, amount, CONVERT(CHAR(10), due_date, 23) FROM ops.scheduled_payments", (),
            lambda rs: (rs.getInt(1), rs.getString(2), Decimal(rs.getBigDecimal(3).toPlainString()),
                        date.fromisoformat(rs.getString(4))),
        )

    def read_backfill_payments(self) -> list[dict]:
        def row(rs):
            v = [rs.getObject(i) for i in range(1, 17)]
            return dict(zip(PAYMENT_COLUMNS, [
                int(v[0]), int(v[1]), int(v[2]), None if v[3] is None else int(v[3]),
                None if v[4] is None else int(v[4]), v[5], _dec(rs.getBigDecimal(7)), v[7], date.fromisoformat(v[8]), v[9],
                v[10], int(v[11]), _ts(v[12]), None if v[13] is None else int(v[13]), _ts(v[14]), _ts(v[15]),
            ]))
        return self._query(BACKFILL_PAYMENTS_SQL, (), row)

    def read_backfill_transactions(self) -> list[dict]:
        def row(rs):
            pid = rs.getObject(4)
            return dict(zip(TRANSACTION_COLUMNS, [
                rs.getLong(1), rs.getInt(2), rs.getInt(3), None if pid is None else int(pid), _ts(rs.getString(5)),
                date.fromisoformat(rs.getString(6)), _dec(rs.getBigDecimal(7)), _dec(rs.getBigDecimal(8)),
                rs.getString(9), rs.getString(10), rs.getString(11),
            ]))
        return self._query(BACKFILL_TRANSACTIONS_SQL, (), row)

    def read_scoring_state(self) -> dict:
        fc = self._query(
            "SELECT model_name, model_version, CONVERT(CHAR(10), MIN(forecast_date), 23) FROM serving.forecast "
            "GROUP BY model_name, model_version", (),
            lambda rs: (rs.getString(1), rs.getString(2), _as_date(rs.getString(3))),
        )
        an = self._query("SELECT DISTINCT model_name, model_version FROM serving.anomalies", (),
                         lambda rs: (rs.getString(1), rs.getString(2)))
        return {"forecast": set(fc), "anomalies": set(an)}

    def replace_scores(self, forecast: list[dict], anomalies: list[dict]) -> None:
        stmts = [("DELETE FROM serving.forecast", [()]), ("DELETE FROM serving.anomalies", [()])]
        if forecast:
            stmts.append((f"INSERT INTO serving.forecast ({', '.join(FORECAST_COLUMNS)}) VALUES ({', '.join('?' * len(FORECAST_COLUMNS))})",
                          [tuple(r[k] for k in FORECAST_COLUMNS) for r in forecast]))
        if anomalies:
            stmts.append((f"INSERT INTO serving.anomalies ({', '.join(ANOMALY_COLUMNS)}) VALUES ({', '.join('?' * len(ANOMALY_COLUMNS))})",
                          [tuple(r[k] for k in ANOMALY_COLUMNS) for r in anomalies]))
        self._transaction(stmts)

    def write_models(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._transaction([
            ("DELETE FROM serving.models WHERE model_name = ?", [(r["model_name"],) for r in rows]),
            (f"INSERT INTO serving.models ({', '.join(MODEL_COLUMNS)}) VALUES ({', '.join('?' * len(MODEL_COLUMNS))})",
             [tuple(r[k] for k in MODEL_COLUMNS) for r in rows]),
        ])

    def write_trace(self, payment_ids, stage: str, at: datetime) -> None:
        ids = sorted({int(p) for p in payment_ids})
        if not ids:
            return
        seen = set(self._query(TRACE_SQL_EXISTING, (stage, ids[0], ids[-1]), lambda rs: rs.getLong(1)))
        rows = [(p, stage, at) for p in ids if p not in seen]
        if rows:
            self._transaction([("INSERT INTO ops.pipeline_trace (payment_id, stage, at) VALUES (?, ?, ?)", rows)])

    def replace_cash_positions(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._transaction([
            ("DELETE FROM serving.cash_position WHERE company_id = ? AND as_of_date = ?",
             [(r["company_id"], r["as_of_date"]) for r in rows]),
            (f"INSERT INTO serving.cash_position ({', '.join(CASH_COLUMNS)}) VALUES ({', '.join('?' * len(CASH_COLUMNS))})",
             [tuple(r[k] for k in CASH_COLUMNS) for r in rows]),
        ])

    def write_run(self, run: dict) -> None:
        self._transaction([
            (f"INSERT INTO ops.pipeline_runs ({', '.join(RUN_COLUMNS)}) VALUES ({', '.join('?' * len(RUN_COLUMNS))})",
             [tuple(run[k] for k in RUN_COLUMNS)]),
        ])


def entra_sql_token(service_credential: str | None) -> Callable[[], str]:
    """Access-token provider for Azure SQL: a Unity Catalog service credential on Databricks,
    else DefaultAzureCredential (managed / workload identity)."""
    scope = "https://database.windows.net/.default"
    if service_credential:
        from databricks.sdk.runtime import dbutils  # type: ignore[import-not-found]

        cred = dbutils.credentials.getServiceCredentialsProvider(service_credential)
    else:
        from azure.identity import DefaultAzureCredential

        cred = DefaultAzureCredential()
    return lambda: cred.get_token(scope).token


def make_store(settings, spark=None):
    if settings.serving_db_url:
        return SqlAlchemyStore(settings.serving_db_url)
    if settings.sql_server:
        return JdbcStore(spark, settings.sql_server, settings.sql_database,
                         entra_sql_token(settings.sql_service_credential))
    raise SystemExit("Set SERVING_DB_URL (local) or SQL_SERVER (Databricks, JDBC + Entra token)")
