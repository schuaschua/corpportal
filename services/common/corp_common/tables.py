"""SQLAlchemy Core table metadata. Mirrors db/schema.sql (the DDL source of truth)."""

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, Index, Integer, MetaData, Numeric, String, Table, Text,
)

metadata = MetaData()

MONEY = Numeric(18, 2, asdecimal=True)

companies = Table(
    "companies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", String(200), nullable=False),
    Column("trade_licence", String(40), nullable=False),
    Column("emirate", String(40), nullable=False),
    Column("industry", String(60), nullable=False),
    schema="ops",
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("company_id", Integer, nullable=False),
    Column("username", String(50), nullable=False),
    Column("display_name", String(100), nullable=False),
    Column("title", String(60), nullable=False),
    Column("role", String(20), nullable=False),
    Column("email", String(200), nullable=False),
    Column("entra_oid", String(64)),
    schema="ops",
)

accounts = Table(
    "accounts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("company_id", Integer, nullable=False),
    Column("name", String(100), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("iban", String(34), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("balance", MONEY, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    schema="ops",
)

beneficiaries = Table(
    "beneficiaries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("company_id", Integer, nullable=False),
    Column("name", String(200), nullable=False),
    Column("iban", String(34), nullable=False),
    Column("category", String(30), nullable=False),
    Column("created_at", DateTime, nullable=False),
    schema="ops",
)

payments = Table(
    "payments", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("company_id", Integer, nullable=False),
    Column("from_account_id", Integer, nullable=False),
    Column("to_account_id", Integer),
    Column("beneficiary_id", Integer),
    Column("amount", MONEY, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("value_date", Date, nullable=False),
    Column("reference", String(140)),
    Column("status", String(20), nullable=False),
    Column("created_by", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("decided_by", Integer),
    Column("decided_at", DateTime),
    Column("executed_at", DateTime),
    schema="ops",
)

transactions = Table(
    "transactions", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("company_id", Integer, nullable=False),
    Column("account_id", Integer, nullable=False),
    Column("payment_id", BigInteger),
    Column("booked_at", DateTime, nullable=False),
    Column("value_date", Date, nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("balance_after", MONEY, nullable=False),
    Column("category", String(30), nullable=False),
    Column("counterparty", String(200), nullable=False),
    Column("description", String(200), nullable=False),
    schema="ops",
)

scheduled_payments = Table(
    "scheduled_payments", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("company_id", Integer, nullable=False),
    Column("from_account_id", Integer, nullable=False),
    Column("beneficiary_id", Integer),
    Column("kind", String(20), nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("due_date", Date, nullable=False),
    Column("description", String(200), nullable=False),
    schema="ops",
)

outbox = Table(
    "outbox", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("company_id", Integer, nullable=False),
    Column("aggregate_type", String(40), nullable=False),
    Column("aggregate_id", String(40), nullable=False),
    Column("event_type", String(60), nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("published_at", DateTime),
    schema="ops",
)

access_log = Table(
    "access_log", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("occurred_at", DateTime, nullable=False),
    Column("user_id", Integer),
    Column("username", String(50)),
    Column("company_id", Integer),
    Column("action", String(40), nullable=False),
    Column("target_type", String(40), nullable=False),
    Column("target_id", String(40), nullable=False),
    Column("detail", String(400)),
    schema="ops",
)

pipeline_trace = Table(
    "pipeline_trace", metadata,
    Column("payment_id", BigInteger, primary_key=True, autoincrement=False),
    Column("stage", String(20), primary_key=True),
    Column("at", DateTime, nullable=False),
    schema="ops",
)

pipeline_runs = Table(
    "pipeline_runs", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", String(64), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime, nullable=False),
    Column("events_ingested", Integer, nullable=False),
    Column("events_new", Integer, nullable=False),
    Column("companies_refreshed", Integer, nullable=False),
    Column("status", String(20), nullable=False),
    Column("next_batch_at", DateTime),
    Index("ix_pipeline_runs_finished", "finished_at"),
    schema="ops",
)

cash_position = Table(
    "cash_position", metadata,
    Column("company_id", Integer, primary_key=True, autoincrement=False),
    Column("as_of_date", Date, primary_key=True),
    Column("total_cash", MONEY, nullable=False),
    Column("available", MONEY, nullable=False),
    Column("scheduled_out_7d", MONEY, nullable=False),
    Column("payroll_due_date", Date),
    Column("payroll_due_amount", MONEY),
    Column("forecast_low", MONEY),
    Column("refreshed_at", DateTime, nullable=False),
    schema="serving",
)

forecast = Table(
    "forecast", metadata,
    Column("company_id", Integer, primary_key=True, autoincrement=False),
    Column("forecast_date", Date, primary_key=True),
    Column("predicted_balance", MONEY, nullable=False),
    Column("lower_bound", MONEY, nullable=False),
    Column("upper_bound", MONEY, nullable=False),
    Column("model_name", String(100), nullable=False),
    Column("model_version", String(40), nullable=False),
    Column("generated_at", DateTime, nullable=False),
    schema="serving",
)

anomalies = Table(
    "anomalies", metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("company_id", Integer, nullable=False),
    Column("payment_id", BigInteger),
    Column("transaction_id", BigInteger),
    Column("occurred_at", DateTime, nullable=False),
    Column("counterparty", String(200), nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("score", Numeric(6, 4, asdecimal=True), nullable=False),
    Column("reason", String(400), nullable=False),
    Column("detected_at", DateTime, nullable=False),
    Column("model_name", String(100), nullable=False),
    Column("model_version", String(40), nullable=False),
    schema="serving",
)

models = Table(
    "models", metadata,
    Column("model_name", String(100), primary_key=True),
    Column("registered_name", String(200), nullable=False),
    Column("model_version", String(40), nullable=False),
    Column("trained_at", DateTime, nullable=False),
    Column("metrics", Text, nullable=False),
    Column("run_id", String(64)),
    schema="serving",
)
