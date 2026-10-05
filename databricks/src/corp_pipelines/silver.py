"""Silver: typed events, one row per outbox id.

  silver.transactions  transaction.posted  (a ledger posting, with the account's balance after)
  silver.payments      payment.executed / payment.rejected

Dedupe is on the outbox id (event_id): duplicates inside bronze collapse to the earliest
ingested copy, and a MERGE inserts only ids silver hasn't seen, so re-running a batch or a
redelivered event changes nothing. New rows carry this batch's run_id, which gold and
serving use to know what moved.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from . import trace
from .lake import GST, Lake

MONEY = "decimal(18,2)"
GST_HOURS = int(GST.total_seconds() // 3600)


def _j(path: str):
    return F.get_json_object(F.col("payload"), path)


def _ts(path: str):
    return F.to_timestamp(_j(path))


def latest_bronze(lake: Lake) -> DataFrame:
    """Bronze deduped on event_id (earliest ingested copy wins), with the payload parsed out."""
    w = Window.partitionBy("event_id").orderBy(F.col("ingested_at"), F.col("source"))
    return (
        lake.read("bronze", "events")
        .where(F.col("event_id").isNotNull())
        .withColumn("_n", F.row_number().over(w))
        .where(F.col("_n") == 1)
        .drop("_n")
        .withColumn("payload", F.get_json_object("body", "$.payload"))
        .withColumn("event_created_at", F.to_timestamp(F.get_json_object("body", "$.created_at")))
    )


def transactions(events: DataFrame, run_id: str) -> DataFrame:
    booked = _ts("$.booked_at")
    return events.where(F.col("event_type") == "transaction.posted").select(
        F.col("event_id"),
        _j("$.id").cast("long").alias("transaction_id"),
        F.col("company_id"),
        _j("$.account_id").cast("int").alias("account_id"),
        _j("$.payment_id").cast("long").alias("payment_id"),
        _j("$.amount").cast(MONEY).alias("amount"),
        _j("$.balance_after").cast(MONEY).alias("balance_after"),
        _j("$.category").alias("category"),
        _j("$.counterparty").alias("counterparty"),
        booked.alias("booked_at"),
        F.to_date(booked + F.expr(f"INTERVAL {GST_HOURS} HOURS")).alias("value_date"),
        F.col("event_created_at"),
        F.lit(run_id).alias("run_id"),
        F.current_timestamp().alias("processed_at"),
    )


def payments(events: DataFrame, run_id: str) -> DataFrame:
    return events.where(F.col("event_type").startswith("payment.")).select(
        F.col("event_id"),
        F.col("aggregate_id").cast("long").alias("payment_id"),
        F.col("company_id"),
        F.col("event_type"),
        _j("$.payment.status").alias("status"),
        _j("$.payment.amount").cast(MONEY).alias("amount"),
        _j("$.payment.currency").alias("currency"),
        F.to_date(_j("$.payment.value_date")).alias("value_date"),
        _j("$.payment.reference").alias("reference"),
        _j("$.payment.from_account.id").cast("int").alias("from_account_id"),
        _j("$.payment.to_account.id").cast("int").alias("to_account_id"),
        _j("$.payment.beneficiary.id").cast("int").alias("beneficiary_id"),
        _j("$.payment.beneficiary.name").alias("beneficiary_name"),
        _j("$.payment.created_by.id").cast("int").alias("created_by"),
        _j("$.payment.decided_by.id").cast("int").alias("decided_by"),
        _ts("$.payment.created_at").alias("created_at"),
        _ts("$.payment.decided_at").alias("decided_at"),
        _ts("$.payment.executed_at").alias("executed_at"),
        F.col("event_created_at"),
        F.lit(run_id).alias("run_id"),
        F.current_timestamp().alias("processed_at"),
    )


def new_rows(lake: Lake, run_id: str) -> DataFrame:
    """(payment_id, company_id) of every silver row this batch inserted."""
    frames = [
        lake.read("silver", t).where(F.col("run_id") == run_id).select("payment_id", "company_id")
        for t in ("transactions", "payments")
        if lake.exists("silver", t)
    ]
    if not frames:
        return lake.spark.createDataFrame([], "payment_id long, company_id int")
    out = frames[0]
    for f in frames[1:]:
        out = out.unionByName(f)
    return out


def run(spark, lake: Lake, store, run_id: str) -> int:
    """Merge new bronze events into silver; trace `silver`. Returns rows inserted."""
    if not lake.exists("bronze", "events"):
        return 0
    events = latest_bronze(lake).cache()
    for table, build in (("transactions", transactions), ("payments", payments)):
        rows = build(events, run_id)
        if lake.exists("silver", table):
            seen = lake.read("silver", table).select("event_id")
            rows = rows.join(seen, "event_id", "left_anti")
            if rows.isEmpty():
                continue  # nothing new: no Delta commit at all
        lake.merge_insert(rows, "silver", table, key="event_id")
    events.unpersist()
    moved = new_rows(lake, run_id).cache()
    count = moved.count()
    if count:
        trace.record(store, trace.payment_ids(moved), "silver")
    moved.unpersist()
    return count
