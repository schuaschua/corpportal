"""Backfill, train and score on the seeded ledger (seed 42): local Spark + Delta, MLflow file
store, SQLite ledger/serving.

Marked `spark`; skipped without pyspark/delta-spark, scikit-learn/MLflow or a working JVM.
They run in the pipelines image (see test_pipelines.py for the command).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from conftest import AS_OF, dataset, outbox_relay
from corp_common import tables as t

pytest.importorskip("pyspark")
pytest.importorskip("delta")
pytest.importorskip("sklearn")
pytest.importorskip("mlflow")
from test_pipelines import _jvm_ok  # noqa: E402

if not _jvm_ok():
    pytest.skip("no working JVM", allow_module_level=True)

pytestmark = pytest.mark.spark

from corp_pipelines import backfill  # noqa: E402
from corp_pipelines.lake import Lake, Settings  # noqa: E402
from corp_pipelines.ml import jobs  # noqa: E402
from corp_pipelines.run_local import run_batch  # noqa: E402
from corp_pipelines.sqlstore import SqlAlchemyStore  # noqa: E402
from test_event_flow import approve_topup  # noqa: E402

PAYROLL_THURSDAY = date(2026, 10, 8)


@pytest.fixture
def ml(spark, db, tmp_path):
    settings = Settings(lake_dir=str(tmp_path / "lake"), landing_dir=str(tmp_path / "landing"),
                        as_of=AS_OF, cadence_seconds=60, ml_seed=42)
    return Lake(spark, settings), SqlAlchemyStore(db)


def forecast(db, company_id=1):
    with db.connect() as conn:
        return conn.execute(select(t.forecast).where(t.forecast.c.company_id == company_id)
                            .order_by(t.forecast.c.forecast_date)).mappings().all()


def anomalies(db):
    with db.connect() as conn:
        return conn.execute(select(t.anomalies).order_by(t.anomalies.c.id)).mappings().all()


def test_backfill_lands_seeded_history_once(spark, db, ml):
    lake, store = ml
    data = dataset()
    first = backfill.run(spark, lake, store, "backfill-1")
    assert first["bronze_appended"] == len(data["payments"]) + len(data["transactions"])
    assert lake.read("silver", "payments").count() == len(data["payments"])
    assert lake.read("silver", "transactions").count() == len(data["transactions"])
    assert lake.read("bronze", "events").where("source = 'seed-payments-1'").count() == 1
    again = backfill.run(spark, lake, store, "backfill-2")
    assert (again["bronze_appended"], again["silver_inserted"]) == (0, 0)
    assert lake.read("bronze", "events").count() == first["bronze_appended"]


def test_train_and_score_flag_planted_anomalies_and_forecast_the_payroll_dip(spark, db, ml):
    lake, store = ml
    backfill.run(spark, lake, store, "backfill-1")
    seeded = forecast(db)
    # No trained model yet: scoring skips and serving keeps the seeded placeholders.
    assert jobs.score(spark, lake, store, "batch-0")["status"] == "skipped"
    assert forecast(db) == seeded and seeded[0]["model_version"] == "seed-0"

    assert jobs.train(spark, lake, store, "train-1") == {"status": "trained", "cash_forecast": "1", "payment_anomaly": "1"}
    assert jobs.score(spark, lake, store, "batch-1")["status"] == "scored"

    planted = {a["payment_id"]: a for a in dataset()["anomalies"]}
    flagged = {a["payment_id"]: a for a in anomalies(db)}
    assert set(planted) <= set(flagged)
    assert len(set(flagged) - set(planted)) <= 5
    assert all(a["model_name"] == "payment_anomaly" and a["model_version"] == "1" and 0 <= a["score"] <= 1
               for a in flagged.values())
    spike = next(p for p, a in planted.items() if a["counterparty"] == "Harbour Freight Co")
    assert flagged[spike]["reason"] == "Unusual: 4× this supplier's average"

    rows = forecast(db)
    assert len(rows) == 30 and rows[0]["forecast_date"] == AS_OF
    assert all(r["lower_bound"] <= r["predicted_balance"] <= r["upper_bound"] for r in rows)
    assert {(r["model_name"], r["model_version"]) for r in rows} == {("cash_forecast", "1")}
    by_day = {r["forecast_date"]: r["predicted_balance"] for r in rows}
    dip = by_day[PAYROLL_THURSDAY - timedelta(days=1)] - by_day[PAYROLL_THURSDAY]
    assert dip > Decimal("1900000") * Decimal("0.8")  # payroll 1.9m leaves on Thursday
    with db.connect() as conn:
        models = {m["model_name"]: m for m in conn.execute(select(t.models)).mappings()}
    assert models["cash_forecast"]["registered_name"] == "corportal.ml.cash_forecast"
    assert models["payment_anomaly"]["model_version"] == "1" and "flag_rate" in models["payment_anomaly"]["metrics"]


def test_approved_topup_lifts_the_forecast_at_the_next_scoring_run(spark, db, ml, payments, tmp_path):
    lake, store = ml
    backfill.run(spark, lake, store, "backfill-1")
    jobs.train(spark, lake, store, "train-1")
    jobs.score(spark, lake, store, "batch-1")
    before = {r["forecast_date"]: r for r in forecast(db)}[PAYROLL_THURSDAY]
    assert jobs.score(spark, lake, store, "batch-1b")["status"] == "unchanged"  # nothing moved

    approve_topup(payments)  # Tom approves Priya's AED 450,000 Reserve -> Operating top-up
    outbox_relay.relay_once(db, outbox_relay.FileSink(lake.settings.landing_dir))
    run_batch(lake.spark, lake, store)
    after = {r["forecast_date"]: r for r in forecast(db)}[PAYROLL_THURSDAY]
    assert abs(after["lower_bound"] - before["lower_bound"] - Decimal("450000")) < Decimal("1000")
    assert after["model_version"] == before["model_version"] == "1"
