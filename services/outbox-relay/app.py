"""outbox-relay: publish ops.outbox rows to Event Hubs in id order (CAP-5 transport).

Every tick it reads up to RELAY_BATCH_SIZE unpublished rows (published_at IS NULL) in id
order, sends them to the sink, and only then sets published_at and writes the `event_hubs`
stage of ops.pipeline_trace. Delivery is at-least-once: if the process dies between the
send and the update, the rows go again next tick and the lake dedupes on the outbox id.
If the send raises, nothing is marked and the next tick retries.

Environment:
  DB_URL                      ledger database (corp_common.db)
  RELAY_SINK                  eventhubs | files
  EVENTHUB_CONNECTION_STRING  eventhubs sink: emulator / tests (takes precedence)
  EVENTHUB_NAMESPACE          eventhubs sink in Azure: <ns>.servicebus.windows.net, with
                              DefaultAzureCredential (workload identity)
  EVENTHUB_NAME               event hub (default: portal-events)
  LANDING_DIR                 files sink: directory for JSON-lines files (local runs)
  RELAY_POLL_SECONDS          tick interval (default 2)
  RELAY_BATCH_SIZE            rows per tick (default 100)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from itertools import groupby
from pathlib import Path

from sqlalchemy import Engine, and_, select, update

from corp_common import tables as t
from corp_common.db import get_engine
from corp_common.scoping import utcnow

log = logging.getLogger("outbox_relay")

STAGE = "event_hubs"


# ------------------------------------------------------------------ events


def envelope(row) -> dict:
    """The message body: the outbox row. `payload` stays the JSON text the service wrote."""
    return {
        "id": int(row["id"]),
        "company_id": int(row["company_id"]),
        "aggregate_type": row["aggregate_type"],
        "aggregate_id": row["aggregate_id"],
        "event_type": row["event_type"],
        "payload": row["payload"],
        "created_at": row["created_at"].isoformat(),
    }


def payment_id_of(event: dict) -> int | None:
    if event["aggregate_type"] == "payment":
        return int(event["aggregate_id"])
    try:
        pid = json.loads(event["payload"]).get("payment_id")
    except (ValueError, AttributeError):
        return None
    return int(pid) if pid is not None else None


# ------------------------------------------------------------------ sinks


class FileSink:
    """JSON lines in LANDING_DIR, one file per batch, renamed into place atomically
    (Spark's file source ignores names starting with '.')."""

    def __init__(self, landing_dir: str | Path):
        self.dir = Path(landing_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, events: list[dict]) -> None:
        name = f"events-{events[0]['id']:012d}-{events[-1]['id']:012d}-{time.time_ns()}.jsonl"
        tmp = self.dir / f".{name}.tmp"
        with tmp.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.dir / name)

    def close(self) -> None:
        pass


class EventHubSink:
    """azure-eventhub producer. Partition key = company, so one company's events stay in order."""

    def __init__(self, connection_string: str | None, namespace: str | None, eventhub: str):
        from azure.eventhub import EventHubProducerClient

        if connection_string:
            self.client = EventHubProducerClient.from_connection_string(connection_string, eventhub_name=eventhub)
        elif namespace:
            from azure.identity import DefaultAzureCredential

            self.client = EventHubProducerClient(
                fully_qualified_namespace=namespace, eventhub_name=eventhub, credential=DefaultAzureCredential()
            )
        else:
            raise SystemExit("RELAY_SINK=eventhubs needs EVENTHUB_CONNECTION_STRING or EVENTHUB_NAMESPACE")

    def send(self, events: list[dict]) -> None:
        from azure.eventhub import EventData

        # Consecutive runs of the same company go in one batch, in id order.
        for company, group in groupby(events, key=lambda e: e["company_id"]):
            batch = self.client.create_batch(partition_key=str(company))
            for e in group:
                data = EventData(json.dumps(e, sort_keys=True))
                data.properties = {"event_type": e["event_type"], "outbox_id": str(e["id"])}
                try:
                    batch.add(data)
                except ValueError:  # batch full
                    self.client.send_batch(batch)
                    batch = self.client.create_batch(partition_key=str(company))
                    batch.add(data)
            self.client.send_batch(batch)

    def close(self) -> None:
        self.client.close()


def make_sink():
    kind = os.environ.get("RELAY_SINK", "eventhubs").lower()
    if kind == "files":
        return FileSink(os.environ.get("LANDING_DIR", "/lake/landing"))
    if kind == "eventhubs":
        return EventHubSink(
            os.environ.get("EVENTHUB_CONNECTION_STRING"),
            os.environ.get("EVENTHUB_NAMESPACE"),
            os.environ.get("EVENTHUB_NAME", "portal-events"),
        )
    raise SystemExit(f"RELAY_SINK must be eventhubs or files, not {kind!r}")


# ------------------------------------------------------------------ relay


def write_trace(conn, payment_ids, stage: str, at) -> None:
    """One row per (payment, stage); a redelivered event doesn't move the first timestamp."""
    ids = sorted(set(payment_ids))
    if not ids:
        return
    seen = set(conn.execute(
        select(t.pipeline_trace.c.payment_id).where(
            and_(t.pipeline_trace.c.stage == stage, t.pipeline_trace.c.payment_id.in_(ids))
        )
    ).scalars())
    rows = [{"payment_id": pid, "stage": stage, "at": at} for pid in ids if pid not in seen]
    if rows:
        conn.execute(t.pipeline_trace.insert(), rows)


def relay_once(engine: Engine, sink, batch_size: int = 100) -> int:
    """Publish one batch. Returns the number of rows marked published (0 on sink failure)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.outbox)
            .where(t.outbox.c.published_at.is_(None))
            .order_by(t.outbox.c.id)
            .limit(batch_size)
        ).mappings().all()
    if not rows:
        return 0
    events = [envelope(r) for r in rows]
    try:
        sink.send(events)
    except Exception:
        log.exception("publish failed for outbox ids %s..%s; will retry", events[0]["id"], events[-1]["id"])
        return 0
    now = utcnow()
    ids = [e["id"] for e in events]
    with engine.begin() as conn:
        conn.execute(
            update(t.outbox)
            .where(and_(t.outbox.c.id.in_(ids), t.outbox.c.published_at.is_(None)))
            .values(published_at=now)
        )
        write_trace(conn, (p for p in map(payment_id_of, events) if p is not None), STAGE, now)
    log.info("published outbox ids %s..%s (%d events)", ids[0], ids[-1], len(ids))
    return len(ids)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    poll = float(os.environ.get("RELAY_POLL_SECONDS", "2"))
    batch_size = int(os.environ.get("RELAY_BATCH_SIZE", "100"))
    sink = make_sink()
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("outbox relay started: sink=%s poll=%ss", type(sink).__name__, poll)
    idle = poll
    try:
        while not stopping:
            try:
                sent = relay_once(get_engine(), sink, batch_size)
            except Exception:  # DB unavailable etc.: keep going
                log.exception("relay tick failed")
                sent = 0
            # Back off while idle (up to 30 s) so an empty outbox costs almost no CPU.
            idle = poll if sent else min(idle * 2, 30.0)
            if sent < batch_size:
                time.sleep(idle)
    finally:
        sink.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
