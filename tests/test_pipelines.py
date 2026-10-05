"""The medallion on tiny inputs: local SparkSession + Delta, SQLite ledger/serving.

Marked `spark`; skipped when pyspark/delta-spark or a working JVM is missing. They run in
the pipelines image, e.g.:
  docker run --rm -u 0 -e HOME=/home/pipelines -v "$PWD":/src -w /src corportal/pipelines:local \
    sh -c 'pip install -q pytest httpx fastapi "pyjwt[crypto]" && pip install -q --no-deps -e services/common \
           && python -m pytest -q --basetemp=/tmp/pytest'
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from conftest import AS_OF, as_user, outbox_relay
from corp_common import tables as t


def _jvm_ok() -> bool:
    try:
        return subprocess.run(["java", "-version"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytest.importorskip("pyspark")
pytest.importorskip("delta")
if not _jvm_ok():
    pytest.skip("no working JVM", allow_module_level=True)

pytestmark = pytest.mark.spark

from corp_pipelines.lake import Lake, Settings  # noqa: E402
from corp_pipelines.run_local import run_batch  # noqa: E402
from corp_pipelines.sqlstore import SqlAlchemyStore  # noqa: E402
from test_event_flow import approve_topup  # noqa: E402


@pytest.fixture
def flow(spark, db, tmp_path):
    settings = Settings(lake_dir=str(tmp_path / "lake"), landing_dir=str(tmp_path / "landing"),
                        as_of=AS_OF, cadence_seconds=60)
    lake, store = Lake(spark, settings), SqlAlchemyStore(db)
    sink = outbox_relay.FileSink(settings.landing_dir)
    return lake, store, sink, lambda: run_batch(spark, lake, store)


def cash_rows(db, company_id=1):
    with db.connect() as conn:
        return conn.execute(select(t.cash_position).where(t.cash_position.c.company_id == company_id)
                            .order_by(t.cash_position.c.as_of_date)).mappings().all()


def test_approve_flows_through_to_serving_and_trace(accounts, payments, db, flow):
    lake, store, sink, batch = flow
    pid = approve_topup(payments)
    before = accounts.get("/dashboard", headers=as_user("priya")).json()
    assert before["available"] == "1780000.00"
    assert outbox_relay.relay_once(db, sink) == 3
    run = batch()
    assert (run["events_ingested"], run["events_new"], run["companies_refreshed"]) == (3, 3, 1)
    dash = accounts.get("/dashboard", headers=as_user("priya")).json()
    assert (dash["as_of"], dash["available"], dash["total_cash"]) == (AS_OF.isoformat(), "2230000.00", "5800000.00")
    assert dash["forecast_low"] == "330000.00" and len(dash["trend"]) == 90
    body = accounts.get(f"/pipeline/trace/{pid}", headers=as_user("priya")).json()
    assert [s["stage"] for s in body["stages"]] == ["ledger", "event_hubs", "bronze", "silver", "gold", "serving"]
    assert body["next_batch_at"] is not None
    # Other companies' serving rows are untouched.
    fabrikam = accounts.get("/dashboard", headers=as_user("omar")).json()
    assert fabrikam["refreshed_at"] == cash_rows(db, fabrikam["company"]["id"])[-1]["refreshed_at"].isoformat()


def test_duplicate_event_lands_once_in_silver(payments, db, flow):
    lake, store, sink, batch = flow
    pid = approve_topup(payments)
    outbox_relay.relay_once(db, sink)
    [f] = Path(lake.settings.landing_dir).glob("events-*")
    shutil.copy(f, f.with_name("events-redelivered.jsonl"))  # at-least-once: the same outbox ids again
    run = batch()
    assert run["events_ingested"] == 6 and run["events_new"] == 3
    assert lake.read("silver", "transactions").count() == 2
    assert lake.read("silver", "payments").where(f"payment_id = {pid}").count() == 1
    assert lake.read("gold", "payment_features").where(f"payment_id = {pid}").count() == 1


def test_batch_with_no_new_events_changes_nothing_but_logs_a_run(payments, db, flow):
    lake, store, sink, batch = flow
    approve_topup(payments)
    outbox_relay.relay_once(db, sink)
    batch()
    serving_before = cash_rows(db)
    silver_version = lake.spark.sql(f"DESCRIBE HISTORY delta.`{lake.path('silver', 'payments')}`").count()
    run = batch()
    assert (run["events_ingested"], run["events_new"], run["companies_refreshed"]) == (0, 0, 0)
    assert cash_rows(db) == serving_before
    assert lake.spark.sql(f"DESCRIBE HISTORY delta.`{lake.path('silver', 'payments')}`").count() == silver_version
    with db.connect() as conn:
        assert conn.execute(select(t.pipeline_runs.c.events_ingested).order_by(t.pipeline_runs.c.id)).scalars().all() == [3, 0]
