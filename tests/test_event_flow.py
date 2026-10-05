"""Outbox relay, the trace endpoint and the serving Available definition (no Spark needed)."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from conftest import AS_OF, as_user, dataset, outbox_relay
from corp_common import tables as t
from corp_pipelines.serving_writer import company_position
from test_apis import create_topup


def approve_topup(payments):
    p = create_topup(payments)
    assert payments.post(f"/payments/{p['id']}/approve", headers=as_user("tom")).status_code == 200
    return p["id"]


def unpublished(db):
    with db.connect() as conn:
        return conn.execute(select(t.outbox.c.id).where(t.outbox.c.published_at.is_(None))).scalars().all()


def test_relay_publishes_in_id_order_and_traces_payment_events(payments, db, tmp_path):
    pid = approve_topup(payments)  # payment.executed + 2 x transaction.posted
    assert len(unpublished(db)) == 3
    sink = outbox_relay.FileSink(tmp_path / "landing")
    assert outbox_relay.relay_once(db, sink) == 3
    [f] = list((tmp_path / "landing").glob("events-*.jsonl"))
    events = [json.loads(line) for line in f.read_text().splitlines()]
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert [e["event_type"] for e in events] == ["payment.executed", "transaction.posted", "transaction.posted"]
    assert unpublished(db) == []
    with db.connect() as conn:
        trace = conn.execute(select(t.pipeline_trace)).mappings().all()
    assert [(r["payment_id"], r["stage"]) for r in trace] == [(pid, "event_hubs")]
    assert outbox_relay.relay_once(db, sink) == 0  # nothing left


def test_relay_sink_down_marks_nothing_and_retries(payments, db, tmp_path):
    approve_topup(payments)

    class Down:
        def send(self, events):
            raise ConnectionError("event hubs unreachable")

    assert outbox_relay.relay_once(db, Down()) == 0
    assert len(unpublished(db)) == 3
    with db.connect() as conn:
        assert conn.execute(select(t.pipeline_trace)).all() == []
    assert outbox_relay.relay_once(db, outbox_relay.FileSink(tmp_path / "landing")) == 3
    assert unpublished(db) == []


def test_trace_lists_reached_stages_and_next_batch(accounts, payments, db, tmp_path):
    pid = approve_topup(payments)
    outbox_relay.relay_once(db, outbox_relay.FileSink(tmp_path / "landing"))
    body = accounts.get(f"/pipeline/trace/{pid}", headers=as_user("priya")).json()
    assert [s["stage"] for s in body["stages"]] == ["ledger", "event_hubs"]
    assert body["next_batch_at"] is None
    finished = datetime.fromisoformat(payments.get(f"/payments/{pid}", headers=as_user("priya")).json()["executed_at"])
    with db.begin() as conn:
        conn.execute(t.pipeline_runs.insert().values(
            run_id="r1", started_at=finished, finished_at=finished, events_ingested=0, events_new=0,
            companies_refreshed=0, status="succeeded", next_batch_at=finished + timedelta(seconds=60)))
    body = accounts.get(f"/pipeline/trace/{pid}", headers=as_user("tom")).json()
    assert body["status"] == "EXECUTED"
    assert body["next_batch_at"] == (finished + timedelta(seconds=60)).isoformat()


def test_trace_for_another_company_is_404_and_logged(accounts, payments, db):
    pid = approve_topup(payments)
    r = accounts.get(f"/pipeline/trace/{pid}", headers=as_user("omar"))
    assert r.status_code == 404
    with db.connect() as conn:
        log = conn.execute(select(t.access_log)).mappings().all()
    assert [(e["username"], e["action"], e["target_type"], e["target_id"]) for e in log] == [
        ("omar", "access_denied", "payment", str(pid))]


def test_serving_available_matches_the_generator_for_every_company():
    data = dataset()
    for c in data["companies"]:
        accts = [(a["kind"], a["balance"]) for a in data["accounts"] if a["company_id"] == c["id"]]
        sched = [(s["kind"], s["amount"], s["due_date"]) for s in data["scheduled_payments"] if s["company_id"] == c["id"]]
        seeded = [p for p in data["cash_position"] if p["company_id"] == c["id"]][-1]
        got = company_position(c["id"], accts, sched, AS_OF, seeded["refreshed_at"])
        assert got == seeded, c["name"]
    nw = [(a["kind"], a["balance"]) for a in data["accounts"] if a["company_id"] == 1]
    moved = [(k, b + Decimal("450000") if k == "operating" else b - Decimal("450000") if k == "reserve" else b) for k, b in nw]
    sched = [(s["kind"], s["amount"], s["due_date"]) for s in data["scheduled_payments"] if s["company_id"] == 1]
    assert company_position(1, moved, sched, AS_OF, None)["available"] == Decimal("2230000.00")
