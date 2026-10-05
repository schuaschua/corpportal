"""Settings and Delta table access, the same code on Databricks and locally.

On Databricks tables live in Unity Catalog as <catalog>.<layer>.<table>; locally
(LAKE_DIR set) each table is a Delta directory at LAKE_DIR/<catalog>/<layer>/<table>.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

GST = timedelta(hours=4)  # business day is Gulf Standard Time, as in the generator

TABLES = {
    ("bronze", "events"),
    ("silver", "transactions"),
    ("silver", "payments"),
    ("gold", "cash_position_daily"),
    ("gold", "payment_features"),
    ("gold", "daily_flows"),
}


def utcnow() -> datetime:
    """Naive UTC, matching the ledger's DATETIME2 columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Settings:
    catalog: str = "corportal"
    lake_dir: str | None = None              # set = local mode
    landing_dir: str = "/lake/landing"
    bronze_source: str = "files"             # files | kafka
    eventhub_namespace: str | None = None    # <ns>.servicebus.windows.net
    eventhub_name: str = "portal-events"
    eventhub_service_credential: str | None = None  # UC service credential (preferred)
    eventhub_secret_scope: str | None = None        # else a connection string in a secret
    eventhub_secret_key: str | None = None
    eventhub_connection_string: str | None = None   # emulator / tests
    checkpoint_volume: str = "checkpoints"   # UC volume under <catalog>.bronze
    serving_db_url: str | None = None        # local: SQLAlchemy URL as pipeline_writer
    sql_server: str | None = None            # Databricks: <server>.database.windows.net (JDBC)
    sql_database: str = "corportal"
    sql_service_credential: str | None = None
    cadence_seconds: int = 300
    as_of: date | None = None                # business date; None = today in Gulf time
    mlflow_tracking_uri: str | None = None   # local: file store; default <LAKE_DIR>/../mlruns
    mlflow_experiment: str | None = None     # default corportal-ml (local), /Shared/corportal-ml (Databricks)
    ml_seed: int = 42                        # training is deterministic for a given seed

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        get = lambda k, d=None: (env.get(k) or d)  # noqa: E731  empty string = unset
        as_of = get("AS_OF")
        return cls(
            catalog=get("CATALOG", "corportal"),
            lake_dir=get("LAKE_DIR"),
            landing_dir=get("LANDING_DIR", "/lake/landing"),
            bronze_source=get("BRONZE_SOURCE", "files").lower(),
            eventhub_namespace=get("EVENTHUB_NAMESPACE"),
            eventhub_name=get("EVENTHUB_NAME", "portal-events"),
            eventhub_service_credential=get("EVENTHUB_SERVICE_CREDENTIAL"),
            eventhub_secret_scope=get("EVENTHUB_SECRET_SCOPE"),
            eventhub_secret_key=get("EVENTHUB_SECRET_KEY"),
            eventhub_connection_string=get("EVENTHUB_CONNECTION_STRING"),
            checkpoint_volume=get("CHECKPOINT_VOLUME", "checkpoints"),
            serving_db_url=get("SERVING_DB_URL"),
            sql_server=get("SQL_SERVER"),
            sql_database=get("SQL_DATABASE", "corportal"),
            sql_service_credential=get("SQL_SERVICE_CREDENTIAL"),
            cadence_seconds=int(get("BATCH_CADENCE_SECONDS", "300")),
            as_of=date.fromisoformat(as_of) if as_of else None,
            mlflow_tracking_uri=get("MLFLOW_TRACKING_URI"),
            mlflow_experiment=get("MLFLOW_EXPERIMENT"),
            ml_seed=int(get("ML_SEED", "42")),
        )

    @property
    def local(self) -> bool:
        return self.lake_dir is not None

    def business_date(self, now: datetime | None = None) -> date:
        return self.as_of or ((now or utcnow()) + GST).date()


def local_spark(app_name: str = "corp-pipelines"):
    """A small local SparkSession with Delta (Dockerfile.local, tests)."""
    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master("local[2]")
        .appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.default.parallelism", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "1g"))
        # Short batches on tiny data: C1-only JIT warms up far faster than C2 here. A bigger
        # code cache keeps the JIT on in a long-lived process (the default 48 MB fills up).
        .config("spark.driver.extraJavaOptions", "-XX:TieredStopAtLevel=1 -XX:ReservedCodeCacheSize=256m")
        .config("spark.databricks.delta.snapshotPartitions", "2")
        # Tiny local tables: Delta data skipping only adds planning (and codegen) time.
        .config("spark.databricks.delta.stats.skipping", "false")
    )
    return configure_spark_with_delta_pip(builder).getOrCreate()


class Lake:
    """Read, append, overwrite and merge the medallion tables by (layer, table)."""

    def __init__(self, spark, settings: Settings):
        self.spark, self.settings = spark, settings

    def name(self, layer: str, table: str) -> str:
        assert (layer, table) in TABLES, (layer, table)
        return f"{self.settings.catalog}.{layer}.{table}"

    def path(self, layer: str, table: str) -> str:
        assert self.settings.local
        return str(Path(self.settings.lake_dir) / self.settings.catalog / layer / table)

    def checkpoint(self, name: str) -> str:
        if self.settings.local:
            return str(Path(self.settings.lake_dir) / self.settings.catalog / "_checkpoints" / name)
        return f"/Volumes/{self.settings.catalog}/bronze/{self.settings.checkpoint_volume}/{name}"

    def exists(self, layer: str, table: str) -> bool:
        from delta.tables import DeltaTable

        if self.settings.local:
            return DeltaTable.isDeltaTable(self.spark, self.path(layer, table))
        return self.spark.catalog.tableExists(self.name(layer, table))

    def read(self, layer: str, table: str):
        if self.settings.local:
            return self.spark.read.format("delta").load(self.path(layer, table))
        return self.spark.read.table(self.name(layer, table))

    def _save(self, writer, layer: str, table: str) -> None:
        if self.settings.local:
            writer.save(self.path(layer, table))
        else:
            writer.saveAsTable(self.name(layer, table))

    def append(self, df, layer: str, table: str) -> None:
        self._save(df.write.format("delta").mode("append"), layer, table)

    def overwrite(self, df, layer: str, table: str, replace_where: str | None = None) -> None:
        w = df.write.format("delta").mode("overwrite")
        if replace_where and self.exists(layer, table):
            w = w.option("replaceWhere", replace_where)
        else:
            w = w.option("overwriteSchema", "true")
        self._save(w, layer, table)

    def merge_insert(self, df, layer: str, table: str, key: str) -> None:
        """Insert rows whose `key` isn't in the table yet (idempotent append)."""
        from delta.tables import DeltaTable

        if not self.exists(layer, table):
            self.append(df, layer, table)
            return
        target = (
            DeltaTable.forPath(self.spark, self.path(layer, table))
            if self.settings.local
            else DeltaTable.forName(self.spark, self.name(layer, table))
        )
        (
            target.alias("t")
            .merge(df.alias("s"), f"t.{key} = s.{key}")
            .whenNotMatchedInsertAll()
            .execute()
        )
