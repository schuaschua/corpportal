"""Backfill: the seeded ledger history into bronze, once, so the models have history to learn.

The generator's 90 days of payments and transactions predate the outbox, so they never
reached the lake. This task reads the ledger rows that no outbox event covers (the seeded
history: executed payments and their postings), wraps each one in the same envelope and
payload the services write, and appends it to bronze.events. Then silver and gold run for
this backfill's run id, like any batch.

Idempotent: each event's key is `seed-<table>-<id>` (bronze `source`) and its outbox id is a
deterministic negative number derived from it, which never collides with a real outbox id.
Events already in bronze are skipped, and silver dedupes on the id as for any redelivery, so
running it again adds nothing.

  corp-pipelines backfill --run-id <id>            (Databricks: the manual corportal-backfill job)
  run_local: once at start-up
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from pyspark.sql import functions as F

from . import bronze, gold, silver
from .lake import Lake

log = logging.getLogger("corp_pipelines.backfill")

SEED_TABLES = {"payments": 1, "transactions": 2}


def seed_key(table: str, row_id: int) -> str:
    return f"seed-{table}-{row_id}"


def seed_event_id(table: str, row_id: int) -> int:
    """bronze.event_id is the outbox id (BIGINT): seed events get -(table code * 10^12 + id)."""
    return -(SEED_TABLES[table] * 10**12 + int(row_id))


def _iso(v):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _money(v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def _ref(obj_id, name=None):
    if obj_id is None:
        return None
    return {"id": int(obj_id), "name": name} if name is not None else {"id": int(obj_id)}


def payment_event(p: dict) -> dict:
    """The payment.executed envelope, with the payload shape payments-api writes."""
    payment = {
        "id": int(p["id"]),
        "status": p["status"],
        "amount": _money(p["amount"]),
        "currency": p["currency"],
        "value_date": _iso(p["value_date"]),
        "reference": p["reference"],
        "from_account": _ref(p["from_account_id"]),
        "to_account": _ref(p["to_account_id"]),
        "beneficiary": _ref(p["beneficiary_id"], p["beneficiary_name"]),
        "created_by": _ref(p["created_by"]),
        "created_at": _iso(p["created_at"]),
        "decided_by": _ref(p["decided_by"]),
        "decided_at": _iso(p["decided_at"]),
        "executed_at": _iso(p["executed_at"]),
    }
    return {
        "id": seed_event_id("payments", p["id"]),
        "company_id": int(p["company_id"]),
        "aggregate_type": "payment",
        "aggregate_id": str(p["id"]),
        "event_type": "payment.executed",
        "payload": json.dumps({"payment": payment, "backfill": True}, sort_keys=True),
        "created_at": _iso(p["executed_at"]),
    }


def transaction_event(t: dict) -> dict:
    """The transaction.posted envelope, with the payload shape payments-api writes."""
    payload = {
        "id": int(t["id"]),
        "company_id": int(t["company_id"]),
        "account_id": int(t["account_id"]),
        "payment_id": None if t["payment_id"] is None else int(t["payment_id"]),
        "amount": _money(t["amount"]),
        "balance_after": _money(t["balance_after"]),
        "category": t["category"],
        "counterparty": t["counterparty"],
        "booked_at": _iso(t["booked_at"]),
        "backfill": True,
    }
    return {
        "id": seed_event_id("transactions", t["id"]),
        "company_id": int(t["company_id"]),
        "aggregate_type": "transaction",
        "aggregate_id": str(t["id"]),
        "event_type": "transaction.posted",
        "payload": json.dumps(payload, sort_keys=True),
        "created_at": _iso(t["booked_at"]),
    }


def seed_events(store) -> list[tuple[str, str]]:
    """(body, source) for every seeded ledger row, payments first."""
    out = [(json.dumps(payment_event(p), sort_keys=True), seed_key("payments", p["id"]))
           for p in store.read_backfill_payments()]
    out += [(json.dumps(transaction_event(t), sort_keys=True), seed_key("transactions", t["id"]))
            for t in store.read_backfill_transactions()]
    return out


def run(spark, lake: Lake, store, run_id: str) -> dict:
    """Append the seed events bronze doesn't have yet, then silver and gold for this run."""
    events = seed_events(store)
    appended = 0
    if events:
        new = bronze.to_bronze(spark.createDataFrame(events, "body string, source string"), run_id)
        if lake.exists("bronze", "events"):
            seen = lake.read("bronze", "events").where(F.col("event_id") < 0).select("event_id")
            new = new.join(seen, "event_id", "left_anti")
        new = new.cache()
        appended = new.count()
        if appended:
            lake.append(new, "bronze", "events")
        new.unpersist()
    inserted = silver.run(spark, lake, store, run_id)
    gold.run(spark, lake, store, run_id)
    result = {"ledger_rows": len(events), "bronze_appended": appended, "silver_inserted": inserted}
    log.info("backfill %s: %s", run_id, result)
    return result
