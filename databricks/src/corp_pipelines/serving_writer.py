"""Serving: gold -> SQL serving.cash_position for the portal dashboard, and the batch's run row.

For every company whose events moved in this batch, the business date's row in
serving.cash_position is replaced (delete + insert, one transaction). The figures use the
piece 1 generator's definitions exactly:

  total_cash        every account
  available         every account except Reserve, minus supplier payments scheduled in
                    the next 7 days (due_date in [as_of, as_of + 7))
  payroll_due       the first scheduled payroll on or after as_of
  forecast_low      available minus that payroll when it is due within 10 days, else available

A batch with no new events writes no serving rows but still writes its ops.pipeline_runs
row, whose next_batch_at drives the portal's "Next batch in mm:ss".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from .lake import Lake, utcnow

ZERO = Decimal("0.00")


def company_position(company_id: int, accounts: Iterable[tuple[str, Decimal]],
                     scheduled: Iterable[tuple[str, Decimal, date]], as_of: date, refreshed_at: datetime) -> dict:
    """One serving.cash_position row. accounts: (kind, balance); scheduled: (kind, amount, due_date)."""
    accounts, scheduled = list(accounts), list(scheduled)
    total = sum((b for _, b in accounts), ZERO)
    non_reserve = sum((b for k, b in accounts if k != "reserve"), ZERO)
    sched_7d = sum((a for k, a, d in scheduled if k == "supplier" and as_of <= d < as_of + timedelta(days=7)), ZERO)
    available = non_reserve - sched_7d
    payroll_days = sorted({d for k, _, d in scheduled if k == "payroll" and d >= as_of})
    due = payroll_days[0] if payroll_days else None
    due_amt = sum((a for k, a, d in scheduled if k == "payroll" and d == due), ZERO) if due else None
    low = available - due_amt if due is not None and (due - as_of).days < 10 else available
    return {
        "company_id": company_id, "as_of_date": as_of, "total_cash": total, "available": available,
        "scheduled_out_7d": sched_7d, "payroll_due_date": due, "payroll_due_amount": due_amt,
        "forecast_low": low, "refreshed_at": refreshed_at,
    }


def positions(gold_rows, scheduled_rows, companies: Iterable[int], as_of: date, refreshed_at: datetime) -> list[dict]:
    """gold_rows: (company_id, account_kind, balance); scheduled_rows: (company_id, kind, amount, due_date)."""
    accts, sched = defaultdict(list), defaultdict(list)
    for cid, kind, bal in gold_rows:
        accts[cid].append((kind, Decimal(str(bal))))
    for cid, kind, amt, due in scheduled_rows:
        sched[cid].append((kind, Decimal(str(amt)), due))
    return [company_position(c, accts[c], sched[c], as_of, refreshed_at) for c in sorted(companies) if accts[c]]


def run(spark, lake: Lake, store, run_id: str, started_at: datetime) -> dict:
    from pyspark.sql import functions as F  # the pure functions above stay importable without Spark

    from . import silver, trace

    moved = silver.new_rows(lake, run_id).cache()
    companies = sorted({int(r[0]) for r in moved.select("company_id").distinct().collect()})
    as_of = lake.settings.business_date(started_at)
    written = []
    if companies and lake.exists("gold", "cash_position_daily"):
        gold = (
            lake.read("gold", "cash_position_daily")
            .where((F.col("position_date") == F.lit(as_of)) & F.col("company_id").isin(companies))
            .select("company_id", "account_kind", "balance")
            .collect()
        )
        written = positions([tuple(r) for r in gold], store.read_scheduled(), companies, as_of, utcnow())
        store.replace_cash_positions(written)
        trace.record(store, trace.payment_ids(moved), "serving")
    events_new = moved.count()
    moved.unpersist()
    events_ingested = (
        lake.read("bronze", "events").where(F.col("run_id") == run_id).count()
        if lake.exists("bronze", "events") else 0
    )
    finished_at = utcnow()
    run_row = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "events_ingested": events_ingested,
        "events_new": events_new,
        "companies_refreshed": len(written),
        "status": "succeeded",
        # Batches start every cadence; one that overran is followed straight away.
        "next_batch_at": max(started_at + timedelta(seconds=lake.settings.cadence_seconds), finished_at),
    }
    store.write_run(run_row)
    return run_row
