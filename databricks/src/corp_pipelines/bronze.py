"""Bronze: every event as it arrived (raw JSON) plus its ingest time, append-only.

Source (BRONZE_SOURCE):
  kafka  Event Hubs' Kafka endpoint (Databricks). Auth: a Unity Catalog service credential
         (EVENTHUB_SERVICE_CREDENTIAL) or a connection string held in a secret scope.
  files  JSON-lines files the relay's files sink writes to LANDING_DIR (local).

Either way it is a Structured Streaming read with trigger(availableNow=True): each batch
drains what is new since the checkpoint and stops, so a batch with nothing new appends
nothing. No always-on cluster. Duplicates (at-least-once relay) are kept here and removed
in silver.
"""

from __future__ import annotations

import os

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType

from . import trace
from .lake import Lake, Settings

ENVELOPE = StructType([
    StructField("id", LongType()),
    StructField("company_id", LongType()),
    StructField("aggregate_type", StringType()),
    StructField("aggregate_id", StringType()),
    StructField("event_type", StringType()),
    StructField("payload", StringType()),
    StructField("created_at", StringType()),
])


def _kafka_options(s: Settings) -> dict:
    if not s.eventhub_namespace:
        raise SystemExit("BRONZE_SOURCE=kafka needs EVENTHUB_NAMESPACE")
    opts = {
        "kafka.bootstrap.servers": f"{s.eventhub_namespace}:9093",
        "subscribe": s.eventhub_name,
        "startingOffsets": "earliest",
        "failOnDataLoss": "false",  # 7-day retention: a long pause must not fail the job
        "kafka.security.protocol": "SASL_SSL",
        "kafka.request.timeout.ms": "60000",
        "kafka.session.timeout.ms": "30000",
    }
    if s.eventhub_service_credential:
        opts["databricks.serviceCredential"] = s.eventhub_service_credential
        return opts
    conn = s.eventhub_connection_string
    if not conn and s.eventhub_secret_scope:
        from databricks.sdk.runtime import dbutils  # type: ignore[import-not-found]

        conn = dbutils.secrets.get(s.eventhub_secret_scope, s.eventhub_secret_key or "eventhub-connection-string")
    if not conn:
        raise SystemExit("Set EVENTHUB_SERVICE_CREDENTIAL, EVENTHUB_SECRET_SCOPE or EVENTHUB_CONNECTION_STRING")
    shaded = "kafkashaded." if os.environ.get("DATABRICKS_RUNTIME_VERSION") else ""
    opts["kafka.sasl.mechanism"] = "PLAIN"
    opts["kafka.sasl.jaas.config"] = (
        f'{shaded}org.apache.kafka.common.security.plain.PlainLoginModule required '
        f'username="$ConnectionString" password="{conn}";'
    )
    return opts


def read_source(spark, s: Settings) -> DataFrame:
    """A streaming frame of (body, source)."""
    if s.bronze_source == "kafka":
        raw = spark.readStream.format("kafka").options(**_kafka_options(s)).load()
        return raw.select(
            F.col("value").cast("string").alias("body"),
            F.concat_ws(":", F.lit("kafka"), F.col("topic"), F.col("partition"), F.col("offset")).alias("source"),
        )
    if s.bronze_source == "files":
        os.makedirs(s.landing_dir, exist_ok=True)
        raw = spark.readStream.format("text").load(s.landing_dir)
        return raw.select(F.col("value").alias("body"), F.input_file_name().alias("source"))
    raise SystemExit(f"BRONZE_SOURCE must be kafka or files, not {s.bronze_source!r}")


def to_bronze(df: DataFrame, run_id: str) -> DataFrame:
    env = F.from_json(F.col("body"), ENVELOPE)
    return (
        df.where(F.length(F.trim(F.col("body"))) > 0)
        .withColumn("env", env)
        .select(
            F.col("env.id").alias("event_id"),
            F.col("env.company_id").cast("int").alias("company_id"),
            F.col("env.event_type").alias("event_type"),
            F.col("env.aggregate_type").alias("aggregate_type"),
            F.col("env.aggregate_id").alias("aggregate_id"),
            F.col("body"),
            F.col("source"),
            F.current_timestamp().alias("ingested_at"),
            F.lit(run_id).alias("run_id"),
        )
    )


def run(spark, lake: Lake, store, run_id: str) -> int:
    """Drain the source into bronze.events; trace `bronze`. Returns rows appended."""
    src = read_source(spark, lake.settings)
    query = (
        src.writeStream.foreachBatch(lambda batch, _id: lake.append(to_bronze(batch, run_id), "bronze", "events"))
        .option("checkpointLocation", lake.checkpoint("bronze_events"))
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()
    if not lake.exists("bronze", "events"):
        return 0
    mine = lake.read("bronze", "events").where(F.col("run_id") == run_id)
    count = mine.count()
    if count:
        ids = trace.payment_ids(
            mine.withColumn("payload", F.get_json_object("body", "$.payload"))
            .withColumn("payment_id", trace.payment_id_col())
        )
        trace.record(store, ids, "bronze")
    return count
