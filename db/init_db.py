"""db-init job: create the database, apply schema.sql, run the generator, apply rls.sql.

Environment:
  DB_URL        target database (the database is created on SQL Server if missing)
  SEED          generator seed (default 42)
  AS_OF         generator as-of date, YYYY-MM-DD (default: today, Gulf Standard Time)
  RESEED        1 = wipe and regenerate even if data already exists (default: keep data)
  SQL_PRINCIPALS
                Azure SQL only: "<Entra name>:<client id>=<role>+<role>,..." contained users
                for the services' workload identities, created from the client ID (WITH SID,
                TYPE = E: no directory lookup, so the server needs no Directory Readers)
  PIPELINE_WRITER_PASSWORD
                SQL Server only: password for the local `pipeline_writer` login the lake
                pipeline connects as (unset = no login is created)

Idempotent: on a second `docker compose up` existing data (including payments made in
the portal) is kept unless RESEED=1.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from corp_common import tables as t
from corp_common.db import create_db_engine
from corp_common.schema import apply_sql_file

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_generator():
    spec = importlib.util.spec_from_file_location("generate", ROOT / "data" / "generator" / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ensure_mssql_database(url: str) -> None:
    u = make_url(url)
    if (u.host or "").endswith(".database.windows.net"):
        return  # Azure SQL: Terraform created the database
    master = create_engine(u.set(database="master"), isolation_level="AUTOCOMMIT")
    for attempt in range(60):
        try:
            with master.connect() as conn:
                conn.execute(
                    text(f"IF DB_ID(N'{u.database}') IS NULL CREATE DATABASE [{u.database}]")
                )
            break
        except Exception as exc:  # SQL Server still starting
            print(f"waiting for SQL Server ({attempt + 1}/60): {str(exc).splitlines()[0][:200]}", flush=True)
            time.sleep(3)
    else:
        raise SystemExit("SQL Server did not become available")
    master.dispose()


PIPELINE_ROLE = "pipeline_writer"        # created by rls.sql; IS_MEMBER() exempts it from RLS
PIPELINE_LOGIN = "pipeline_writer"       # local SQL login (in Azure: the Databricks identity)
PIPELINE_USER = "pipeline_writer_local"  # a database user can't share the role's name


def grant_pipeline_writer(engine, password: str | None) -> None:
    """Role grants (every environment) and, locally, a SQL login + user in the role.

    The pipeline reads ops (accounts, scheduled payments), writes serving and its own
    ops.pipeline_* tables, and nothing else.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"IF DATABASE_PRINCIPAL_ID(N'{PIPELINE_ROLE}') IS NULL CREATE ROLE {PIPELINE_ROLE}"
        )
        conn.exec_driver_sql(f"GRANT SELECT ON SCHEMA::ops TO {PIPELINE_ROLE}")
        conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::serving TO {PIPELINE_ROLE}")
        conn.exec_driver_sql(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ops.pipeline_trace TO {PIPELINE_ROLE}"
        )
        conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE ON ops.pipeline_runs TO {PIPELINE_ROLE}")
        if not password:
            print("PIPELINE_WRITER_PASSWORD not set: no local pipeline_writer login created")
            return
        pw = password.replace("'", "''")
        conn.exec_driver_sql(
            f"IF SUSER_ID(N'{PIPELINE_LOGIN}') IS NULL "
            f"CREATE LOGIN {PIPELINE_LOGIN} WITH PASSWORD = N'{pw}' "
            f"ELSE ALTER LOGIN {PIPELINE_LOGIN} WITH PASSWORD = N'{pw}'"
        )
        conn.exec_driver_sql(
            f"IF DATABASE_PRINCIPAL_ID(N'{PIPELINE_USER}') IS NULL "
            f"CREATE USER {PIPELINE_USER} FOR LOGIN {PIPELINE_LOGIN} WITH DEFAULT_SCHEMA = ops"
        )
        conn.exec_driver_sql(
            f"IF IS_ROLEMEMBER(N'{PIPELINE_ROLE}', N'{PIPELINE_USER}') = 0 "
            f"ALTER ROLE {PIPELINE_ROLE} ADD MEMBER {PIPELINE_USER}"
        )
    print(f"login {PIPELINE_LOGIN} (user {PIPELINE_USER}) is a member of {PIPELINE_ROLE}")


def _entra_sid(client_id: str) -> str:
    """The SID Azure SQL gives an Entra app / managed identity: its client ID's GUID bytes."""
    return "0x" + uuid.UUID(client_id).bytes_le.hex().upper()


def grant_entra_principals(engine, spec: str | None) -> None:
    """Azure SQL: one contained user per Entra identity (by client ID), in its roles."""
    for item in filter(None, (x.strip() for x in (spec or "").split(","))):
        principal, _, roles = item.partition("=")
        name, _, client_id = principal.partition(":")
        str(uuid.UUID(client_id))  # validates before it reaches SQL
        quoted = name.replace("]", "]]")
        with engine.begin() as conn:
            conn.exec_driver_sql(
                f"IF DATABASE_PRINCIPAL_ID(N'{name}') IS NULL CREATE USER [{quoted}] "
                f"WITH SID = {_entra_sid(client_id)}, TYPE = E"
            )
            for role in filter(None, roles.split("+")):
                conn.exec_driver_sql(
                    f"IF IS_ROLEMEMBER(N'{role}', N'{name}') = 0 ALTER ROLE [{role}] ADD MEMBER [{quoted}]"
                )
        print(f"Entra user {name}: {roles}")


def migrate_for_ml(engine) -> None:
    """Databases seeded before piece 4: add serving.models and the anomalies' model columns
    (the seeded rows are the generator's placeholders, `payment-anomaly-baseline` seed-0)."""
    t.metadata.create_all(engine, tables=[t.models], checkfirst=True)
    cols = {c["name"] for c in inspect(engine).get_columns("anomalies", schema="serving")}
    if "model_name" in cols:
        return
    with engine.begin() as conn:
        if engine.dialect.name == "mssql":
            conn.exec_driver_sql("DROP SECURITY POLICY IF EXISTS ops.company_isolation")  # rls.sql re-applies it
            conn.exec_driver_sql("ALTER TABLE serving.anomalies ADD model_name NVARCHAR(100) NULL, model_version NVARCHAR(40) NULL")
        else:
            conn.exec_driver_sql("ALTER TABLE serving.anomalies ADD COLUMN model_name VARCHAR(100)")
            conn.exec_driver_sql("ALTER TABLE serving.anomalies ADD COLUMN model_version VARCHAR(40)")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE serving.anomalies SET model_name = 'payment-anomaly-baseline', model_version = 'seed-0' "
            "WHERE model_name IS NULL"
        )
    print("serving.anomalies: model_name/model_version added")


def main() -> int:
    url = os.environ["DB_URL"]
    mssql = url.startswith("mssql")
    if mssql:
        ensure_mssql_database(url)
    engine = create_db_engine(url)

    seeded = False
    if inspect(engine).has_table("companies", schema="ops"):
        with engine.connect() as conn:
            seeded = conn.execute(text("SELECT COUNT(*) FROM ops.companies")).scalar_one() > 0
    if seeded and os.environ.get("RESEED") != "1":
        print("data already present; keeping it (set RESEED=1 to regenerate)")
        # Databases seeded before piece 3 lack the pipeline tables, before piece 4 the ML ones.
        t.metadata.create_all(engine, tables=[t.pipeline_trace, t.pipeline_runs], checkfirst=True)
        migrate_for_ml(engine)
    else:
        if mssql:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP SECURITY POLICY IF EXISTS ops.company_isolation")
        apply_sql_file(engine, HERE / "schema.sql")
        gen = load_generator()
        as_of = os.environ.get("AS_OF")
        as_of = date.fromisoformat(as_of) if as_of else (datetime.now(timezone.utc) + gen.GST).date()
        data = gen.generate(int(os.environ.get("SEED", "42")), as_of)
        gen.load(engine, data)
        print(f"generated seed={os.environ.get('SEED', '42')} as_of={as_of} digest={gen.digest(data)}")
    if mssql:
        apply_sql_file(engine, HERE / "rls.sql")
        print("row-level security applied")
        grant_pipeline_writer(engine, os.environ.get("PIPELINE_WRITER_PASSWORD"))
        grant_entra_principals(engine, os.environ.get("SQL_PRINCIPALS"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
