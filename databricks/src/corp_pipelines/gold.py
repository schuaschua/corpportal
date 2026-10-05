"""Gold: the business views, recomputed from silver whenever silver moved.

gold.cash_position_daily  one row per account per business date, with its company and
                          kind. The balance is the lake's latest `balance_after` for the
                          account (latest = highest ledger transaction id, the posting
                          order); accounts with no event in the lake yet fall back to the
                          ledger's reference balance. The business date's partition is
                          replaced each time.
gold.payment_features     one row per executed payment: amount, ratio to the beneficiary's
                          mean so far, Gulf hour and weekend flag, first-time beneficiary,
                          same-day duplicate count. The anomaly model's input (ml/anomaly.py).
gold.daily_flows          one row per company per Gulf business day: the net flow of its
                          non-Reserve accounts split into other (customers, fees, ...),
                          supplier, payroll and transfer. The cash forecast's input
                          (ml/forecast.py).
"""

from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from . import silver, trace
from .lake import GST, Lake, utcnow

GST_HOURS = int(GST.total_seconds() // 3600)
MONEY = "decimal(18,2)"
# A beneficiary's first payment counts as "first-time" only once the lake holds this much of
# the company's history; before that, a first payment in the lake is just the history's start.
FIRST_TIME_AFTER_DAYS = 28


def reference_accounts(spark, store) -> DataFrame:
    rows = [(a, c, k, b) for a, c, k, b in store.read_accounts()]
    return spark.createDataFrame(rows, "account_id int, company_id int, account_kind string, reference_balance decimal(18,2)")


def cash_position_daily(spark, lake: Lake, store, business_date, run_id: str) -> DataFrame:
    accounts = reference_accounts(spark, store)
    if lake.exists("silver", "transactions"):
        w = Window.partitionBy("account_id").orderBy(F.col("transaction_id").desc())
        latest = (
            lake.read("silver", "transactions")
            .withColumn("_n", F.row_number().over(w))
            .where(F.col("_n") == 1)
            .select("account_id", F.col("balance_after").alias("lake_balance"), F.col("booked_at").alias("last_booked_at"))
        )
    else:
        latest = spark.createDataFrame([], "account_id int, lake_balance decimal(18,2), last_booked_at timestamp")
    return (
        accounts.join(latest, "account_id", "left")
        .select(
            F.lit(business_date).cast("date").alias("position_date"),
            "company_id",
            "account_id",
            "account_kind",
            F.coalesce("lake_balance", "reference_balance").cast(MONEY).alias("balance"),
            F.when(F.col("lake_balance").isNotNull(), "lake").otherwise("reference").alias("balance_source"),
            "last_booked_at",
            F.lit(utcnow()).alias("computed_at"),
            F.lit(run_id).alias("run_id"),
        )
    )


def payment_features(lake: Lake, run_id: str) -> DataFrame:
    pay = lake.read("silver", "payments").where(F.col("status") == "EXECUTED")
    pay = pay.withColumn("_n", F.row_number().over(Window.partitionBy("payment_id").orderBy("event_id"))).where("_n = 1")
    if lake.exists("silver", "transactions"):
        debit = (
            lake.read("silver", "transactions")
            .where(F.col("payment_id").isNotNull() & (F.col("amount") < 0))
            .groupBy("payment_id")
            .agg(F.min("transaction_id").alias("transaction_id"))
        )
        pay = pay.join(debit, "payment_id", "left")
    else:
        pay = pay.withColumn("transaction_id", F.lit(None).cast("long"))
    local = F.col("executed_at") + F.expr(f"INTERVAL {GST_HOURS} HOURS")
    ben = Window.partitionBy("company_id", "beneficiary_id").orderBy("executed_at", "payment_id")
    prior = ben.rowsBetween(Window.unboundedPreceding, -1)
    company = Window.partitionBy("company_id")
    # Same beneficiary (or own account), same amount, same value date, executed earlier.
    twins = (
        Window.partitionBy("company_id", "beneficiary_id", "to_account_id", "amount", "value_date")
        .orderBy("executed_at", "payment_id")
        .rowsBetween(Window.unboundedPreceding, -1)
    )
    prior_count = F.count("payment_id").over(prior)
    return pay.select(
        "payment_id",
        "company_id",
        "transaction_id",
        "from_account_id",
        "to_account_id",
        "beneficiary_id",
        F.coalesce("beneficiary_name", F.lit("Own account transfer")).alias("counterparty"),
        "amount",
        "value_date",
        "executed_at",
        F.log1p(F.col("amount").cast("double")).alias("log_amount"),
        F.hour(local).alias("hour_gst"),
        F.dayofweek(local).alias("day_of_week_gst"),  # 1 = Sunday
        F.dayofweek(local).isin(1, 7).alias("is_weekend"),  # UAE weekend: Saturday, Sunday
        F.col("to_account_id").isNotNull().alias("is_internal"),
        F.when(F.col("beneficiary_id").isNull(), None).otherwise(prior_count).alias("beneficiary_prior_count"),
        F.when(F.col("beneficiary_id").isNull(), None).otherwise(F.avg("amount").over(prior)).cast(MONEY).alias("beneficiary_prior_mean"),
        (
            F.col("beneficiary_id").isNotNull()
            & (prior_count == 0)
            & (F.col("executed_at") >= F.min("executed_at").over(company) + F.expr(f"INTERVAL {FIRST_TIME_AFTER_DAYS} DAYS"))
        ).alias("is_first_time_beneficiary"),
        F.count("payment_id").over(twins).alias("same_day_duplicates"),
        F.lit(run_id).alias("run_id"),
        F.current_timestamp().alias("computed_at"),
    ).withColumn(
        "amount_to_prior_mean",
        F.when(F.col("beneficiary_prior_mean") > 0, F.col("amount") / F.col("beneficiary_prior_mean")).cast("double"),
    )


def daily_flows(spark, lake: Lake, store, run_id: str) -> DataFrame:
    """Net flow of each company's non-Reserve accounts per Gulf business day, by bucket.

    Transfers between non-Reserve accounts net to zero; transfers from or to Reserve are
    treasury moves, kept apart so the forecast baseline doesn't learn them."""
    kinds = reference_accounts(spark, store).select("account_id", "account_kind")
    tx = (
        lake.read("silver", "transactions")
        .dropDuplicates(["transaction_id"])
        .join(kinds, "account_id")
        .where(F.col("account_kind") != "reserve")
    )
    cat = F.col("category")
    bucket = (
        F.when(cat == "supplier", "supplier")
        .when(cat == "payroll", "payroll")
        .when(cat == "transfer", "transfer")
        .otherwise("other")
    )
    total = lambda name: F.sum(F.when(bucket == name, F.col("amount")).otherwise(0)).cast(MONEY)  # noqa: E731
    return (
        tx.groupBy("company_id", F.col("value_date").alias("flow_date"))
        .agg(
            total("other").alias("other_net"),
            total("supplier").alias("supplier_net"),
            total("payroll").alias("payroll_net"),
            total("transfer").alias("transfer_net"),
            F.sum("amount").cast(MONEY).alias("total_net"),
        )
        .withColumn("run_id", F.lit(run_id))
        .withColumn("computed_at", F.current_timestamp())
    )


def run(spark, lake: Lake, store, run_id: str) -> int:
    """Recompute gold if silver moved in this batch (or a gold table doesn't exist yet);
    trace `gold`. Returns the number of payments traced."""
    moved = silver.new_rows(lake, run_id).cache()
    fresh = moved.count() > 0
    missing = not lake.exists("gold", "cash_position_daily") or (
        lake.exists("silver", "transactions") and not lake.exists("gold", "daily_flows")
    )
    if not fresh and not missing:
        moved.unpersist()
        return 0
    business_date = lake.settings.business_date()
    cash = cash_position_daily(spark, lake, store, business_date, run_id)
    lake.overwrite(cash, "gold", "cash_position_daily", replace_where=f"position_date = DATE'{business_date.isoformat()}'")
    if lake.exists("silver", "payments"):
        lake.overwrite(payment_features(lake, run_id), "gold", "payment_features")
    if lake.exists("silver", "transactions"):
        lake.overwrite(daily_flows(spark, lake, store, run_id), "gold", "daily_flows")
    traced = trace.record(store, trace.payment_ids(moved), "gold") if fresh else 0
    moved.unpersist()
    return traced
