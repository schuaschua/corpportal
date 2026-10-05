"""Local medallion loop (compose `pipelines` service, Dockerfile.local).

Runs bronze -> silver -> gold -> score -> serving every BATCH_CADENCE_SECONDS in one
long-lived local SparkSession, reading the relay's files from LANDING_DIR and keeping Delta
tables under LAKE_DIR. Each batch drains what is new (availableNow) and stops; nothing
streams between batches.

At start-up it backfills the seeded ledger history (idempotent: nothing the second time)
and trains the models once if none is registered yet (MLflow file store in the lake volume).

  python -m corp_pipelines.run_local           # loop
  python -m corp_pipelines.run_local --once    # one batch
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import uuid
from datetime import datetime

from . import backfill, bronze, gold, serving_writer, silver
from .ml import jobs as ml_jobs
from .ml import registry
from .lake import Lake, Settings, local_spark, utcnow
from .sqlstore import make_store

log = logging.getLogger("corp_pipelines")


def new_run_id(now: datetime) -> str:
    return f"local-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def run_batch(spark, lake: Lake, store, run_id: str | None = None, started_at: datetime | None = None) -> dict:
    """One batch: every stage in order. Returns the ops.pipeline_runs row it wrote."""
    started_at = started_at or utcnow()
    run_id = run_id or new_run_id(started_at)
    ingested = bronze.run(spark, lake, store, run_id)
    new = silver.run(spark, lake, store, run_id)
    gold.run(spark, lake, store, run_id)
    try:
        ml_jobs.score(spark, lake, store, run_id)
    except Exception:  # a scoring failure must not hold back the cash position
        log.exception("score failed; serving.forecast and serving.anomalies left as they were")
    row = serving_writer.run(spark, lake, store, run_id, started_at)
    log.info("batch %s: bronze +%d, silver +%d, serving companies %d", run_id, ingested, new, row["companies_refreshed"])
    return row


def start_up(spark, lake: Lake, store) -> None:
    """Seeded history into the lake (once), and a first model if the registry has none."""
    now = utcnow()
    backfill.run(spark, lake, store, f"backfill-{now:%Y%m%dT%H%M%S}")
    registry.configure(lake.settings)
    if any(registry.load_champion(lake.settings, n) is None for n in ("cash_forecast", "payment_anomaly")):
        ml_jobs.train(spark, lake, store, f"train-{now:%Y%m%dT%H%M%S}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="run one batch and exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    if not settings.local:
        raise SystemExit("run_local needs LAKE_DIR")
    spark = local_spark()
    spark.sparkContext.setLogLevel("WARN")
    lake, store = Lake(spark, settings), make_store(settings, spark)

    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("pipelines started: cadence=%ss lake=%s landing=%s", settings.cadence_seconds, settings.lake_dir, settings.landing_dir)
    try:
        start_up(spark, lake, store)
    except Exception:
        log.exception("backfill/train at start-up failed; batches continue without a model")
    while True:
        tick = time.monotonic()
        try:
            run_batch(spark, lake, store)
        except Exception:
            log.exception("batch failed; retrying next cadence")
        if args.once:
            break
        while not stopping and time.monotonic() - tick < settings.cadence_seconds:
            time.sleep(0.5)
        if stopping:
            break
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
