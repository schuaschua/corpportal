"""Stage tracing: which payments each batch moved through bronze, silver, gold and serving.

The outbox relay writes `event_hubs`; the portal's drawer reads the rows through
accounts-api GET /pipeline/trace/{payment_id}. One row per (payment, stage): a
redelivered event never moves the first timestamp.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from .lake import utcnow

STAGES = ("event_hubs", "bronze", "silver", "gold", "serving")


def payment_id_col(aggregate_type: str = "aggregate_type", aggregate_id: str = "aggregate_id",
                   payload: str = "payload") -> Column:
    """The payment an event belongs to: the aggregate for payment.*, payload.payment_id otherwise."""
    return F.when(F.col(aggregate_type) == "payment", F.col(aggregate_id).cast("long")).otherwise(
        F.get_json_object(F.col(payload), "$.payment_id").cast("long")
    )


def payment_ids(df: DataFrame, column: str = "payment_id") -> list[int]:
    return [int(r[0]) for r in df.select(column).where(F.col(column).isNotNull()).distinct().collect()]


def record(store, ids, stage: str) -> int:
    """Write `stage` for these payments now. Returns how many payments were traced."""
    assert stage in STAGES, stage
    ids = sorted(set(ids))
    store.write_trace(ids, stage, utcnow())
    return len(ids)
