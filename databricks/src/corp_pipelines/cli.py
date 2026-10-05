"""Databricks job task entry point: one task per medallion stage, plus the ML tasks.

  corp-pipelines <bronze|silver|gold|score|serving> --run-id {{job.run_id}}
      --started-at {{job.start_time.iso_datetime}} [KEY=VALUE ...]
  corp-pipelines backfill --run-id ...   seeded ledger history -> bronze/silver/gold, once
  corp-pipelines train --run-id ...      fit, log to MLflow, register in Unity Catalog

KEY=VALUE pairs are the same settings as the environment variables (CATALOG,
BRONZE_SOURCE, EVENTHUB_NAMESPACE, SQL_SERVER, BATCH_CADENCE_SECONDS, ...); databricks.yml
passes the bundle variables this way. Every task of one job run shares the run id, so each
stage picks up exactly what the previous one moved.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from . import backfill, bronze, gold, serving_writer, silver
from .lake import Lake, Settings, utcnow
from .sqlstore import make_store


def _started_at(value: str | None) -> datetime:
    if not value:
        return utcnow()
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="corp-pipelines")
    ap.add_argument("stage", choices=["bronze", "silver", "gold", "score", "serving", "backfill", "train"])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--started-at")
    ap.add_argument("settings", nargs="*", metavar="KEY=VALUE")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    env = dict(os.environ)
    for pair in args.settings:
        key, sep, value = pair.partition("=")
        if not sep:
            ap.error(f"expected KEY=VALUE, got {pair!r}")
        env[key] = value
    settings = Settings.from_env(env)

    if settings.local:  # e.g. `docker compose exec pipelines python -m corp_pipelines.cli train ...`
        from .lake import local_spark

        spark = local_spark()
    else:
        from pyspark.sql import SparkSession

        spark = SparkSession.builder.getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    lake, store = Lake(spark, settings), make_store(settings, spark)
    run_id = f"job-{args.run_id}"
    if args.stage == "bronze":
        result = bronze.run(spark, lake, store, run_id)
    elif args.stage == "silver":
        result = silver.run(spark, lake, store, run_id)
    elif args.stage == "gold":
        result = gold.run(spark, lake, store, run_id)
    elif args.stage == "backfill":
        result = backfill.run(spark, lake, store, run_id)
    elif args.stage in ("train", "score"):
        from .ml import jobs  # pandas / scikit-learn / MLflow only where needed

        result = jobs.train(spark, lake, store, run_id) if args.stage == "train" else jobs.score(spark, lake, store, run_id)
    else:
        result = serving_writer.run(spark, lake, store, run_id, _started_at(args.started_at))
    logging.getLogger("corp_pipelines").info("%s %s: %s", args.stage, run_id, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
