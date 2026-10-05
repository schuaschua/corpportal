"""Lake pipelines for the Corporate Portal PoC (piece 3, CAP-5) and its ML (piece 4, CAP-7/8).

bronze.py        raw events from Event Hubs (Kafka endpoint) or a landing dir, + ingest time
silver.py        typed, deduped on the outbox id: silver.transactions, silver.payments
gold.py          gold.cash_position_daily (per account, per company), gold.payment_features,
                 gold.daily_flows
backfill.py      the seeded ledger history into bronze, once (ids seed-<table>-<id>)
ml/              cash forecast + Isolation Forest: train (MLflow, Unity Catalog), score -> serving
serving_writer.py  gold -> SQL serving.cash_position, plus the per-batch ops.pipeline_runs row
trace.py         ops.pipeline_trace stages
run_local.py     the local batch loop (compose `pipelines` service)
cli.py           Databricks job task entry point (one task per stage)
"""
