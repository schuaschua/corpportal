"""accounts-api: read endpoints for the caller's company (CAP-1, CAP-2, CAP-3, CAP-5 trace).

The cash forecast and the anomaly details are served by insights-api (GET /forecast,
/anomalies, /models); the dashboard here still lists the flagged payments of its window.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from fastapi import Depends, Query
from sqlalchemy import and_, func, select

from corp_common import tables as t
from corp_common.app_factory import create_app
from corp_common.auth import User, current_user
from corp_common.db import company_connection
from corp_common.scoping import Denied, money

app = create_app("accounts-api")


def _account(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "iban": row["iban"],
        "currency": row["currency"],
        "balance": money(row["balance"]),
        "updated_at": row["updated_at"].isoformat(),
    }


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "title": user.title,
        "role": user.role,
        "email": user.email,
        "company": {"id": user.company_id, "name": user.company_name},
    }


@app.get("/accounts")
def list_accounts(user: User = Depends(current_user)):
    with company_connection(user.company_id) as conn:
        rows = conn.execute(
            select(t.accounts).where(t.accounts.c.company_id == user.company_id).order_by(t.accounts.c.id)
        ).mappings().all()
    return {"accounts": [_account(r) for r in rows]}


@app.get("/accounts/{account_id}")
def get_account(account_id: int, user: User = Depends(current_user)):
    with company_connection(user.company_id) as conn:
        row = conn.execute(
            select(t.accounts).where(
                and_(t.accounts.c.id == account_id, t.accounts.c.company_id == user.company_id)
            )
        ).mappings().first()
        if row is None:
            raise Denied(user, "account", account_id)
    return _account(row)


@app.get("/accounts/{account_id}/transactions")
def account_transactions(
    account_id: int,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(current_user),
):
    with company_connection(user.company_id) as conn:
        acct = conn.execute(
            select(t.accounts).where(
                and_(t.accounts.c.id == account_id, t.accounts.c.company_id == user.company_id)
            )
        ).mappings().first()
        if acct is None:
            raise Denied(user, "account", account_id)
        rows = conn.execute(
            select(t.transactions)
            .where(
                and_(
                    t.transactions.c.account_id == account_id,
                    t.transactions.c.company_id == user.company_id,
                )
            )
            .order_by(t.transactions.c.booked_at.desc(), t.transactions.c.id.desc())
            .limit(limit)
        ).mappings().all()
    return {
        "account": _account(acct),
        "transactions": [
            {
                "id": r["id"],
                "booked_at": r["booked_at"].isoformat(),
                "value_date": r["value_date"].isoformat(),
                "amount": money(r["amount"]),
                "balance_after": money(r["balance_after"]),
                "category": r["category"],
                "counterparty": r["counterparty"],
                "description": r["description"],
                "payment_id": r["payment_id"],
            }
            for r in rows
        ],
    }


@app.get("/dashboard")
def dashboard(user: User = Depends(current_user)):
    """Serving-layer KPIs, trend and anomalies, plus live operational balances.

    The KPI figures come from serving.cash_position (refreshed by the lake pipeline in
    piece 3); `operational` is read straight from the ledger so an executed payment shows
    immediately.
    """
    cid = user.company_id
    with company_connection(cid) as conn:
        positions = conn.execute(
            select(t.cash_position)
            .where(t.cash_position.c.company_id == cid)
            .order_by(t.cash_position.c.as_of_date)
        ).mappings().all()
        latest = positions[-1] if positions else None
        anomalies = []
        if latest is not None:
            since = datetime.combine(latest["as_of_date"] - timedelta(days=30), time.min)
            anomalies = conn.execute(
                select(t.anomalies)
                .where(and_(t.anomalies.c.company_id == cid, t.anomalies.c.occurred_at >= since))
                .order_by(t.anomalies.c.occurred_at.desc())
            ).mappings().all()
        accounts = conn.execute(
            select(t.accounts).where(t.accounts.c.company_id == cid).order_by(t.accounts.c.id)
        ).mappings().all()
        as_of = latest["as_of_date"] if latest is not None else None
        scheduled_7d = 0
        if as_of is not None:
            scheduled_7d = conn.execute(
                select(func.coalesce(func.sum(t.scheduled_payments.c.amount), 0)).where(
                    and_(
                        t.scheduled_payments.c.company_id == cid,
                        t.scheduled_payments.c.kind == "supplier",
                        t.scheduled_payments.c.due_date >= as_of,
                        t.scheduled_payments.c.due_date < as_of + timedelta(days=7),
                    )
                )
            ).scalar_one()

    total_live = sum((Decimal(str(a["balance"])) for a in accounts), Decimal("0"))
    non_reserve_live = sum(
        (Decimal(str(a["balance"])) for a in accounts if a["kind"] != "reserve"), Decimal("0")
    )
    return {
        "company": {"id": cid, "name": user.company_name},
        "currency": "AED",
        "as_of": as_of.isoformat() if as_of else None,
        "total_cash": money(latest["total_cash"]) if latest else None,
        "available": money(latest["available"]) if latest else None,
        "scheduled_out_7d": money(latest["scheduled_out_7d"]) if latest else None,
        "forecast_low": money(latest["forecast_low"]) if latest else None,
        "payroll_due": (
            {"date": latest["payroll_due_date"].isoformat(), "amount": money(latest["payroll_due_amount"])}
            if latest and latest["payroll_due_date"]
            else None
        ),
        "refreshed_at": latest["refreshed_at"].isoformat() if latest else None,
        # non_reserve (available + the 7 days' scheduled supplier payments) is the basis the
        # forecast projects, so the chart's actual line meets the forecast at Today.
        "trend": [
            {
                "date": p["as_of_date"].isoformat(),
                "total_cash": money(p["total_cash"]),
                "available": money(p["available"]),
                "non_reserve": money(Decimal(str(p["available"])) + Decimal(str(p["scheduled_out_7d"]))),
            }
            for p in positions
        ],
        "anomalies": [
            {
                "id": a["id"],
                "payment_id": a["payment_id"],
                "occurred_at": a["occurred_at"].isoformat(),
                "counterparty": a["counterparty"],
                "amount": money(a["amount"]),
                "score": str(a["score"]),
                "reason": a["reason"],
            }
            for a in anomalies
        ],
        "operational": {
            "total_cash": money(total_live),
            "available": money(non_reserve_live - Decimal(str(scheduled_7d))),
            "accounts": [_account(a) for a in accounts],
        },
    }


TRACE_STAGES = ("ledger", "event_hubs", "bronze", "silver", "gold", "serving")


@app.get("/pipeline/trace/{payment_id}")
def pipeline_trace(payment_id: int, user: User = Depends(current_user)):
    """How far one of the caller's payments has travelled: ledger -> Event Hubs -> bronze ->
    silver -> gold -> serving (CAP-5), plus when the next lake batch is due.

    `stages` lists only the stages reached, in order. The ledger stage is the payment's
    execution; the others are written by the outbox relay and the lake pipeline. A payment
    of another company is a 404 with an access_denied audit row.
    """
    cid = user.company_id
    with company_connection(cid) as conn:
        pay = conn.execute(
            select(t.payments.c.id, t.payments.c.status, t.payments.c.executed_at).where(
                and_(t.payments.c.id == payment_id, t.payments.c.company_id == cid)
            )
        ).mappings().first()
        if pay is None:
            raise Denied(user, "payment", payment_id)
        rows = conn.execute(
            select(t.pipeline_trace.c.stage, t.pipeline_trace.c.at).where(t.pipeline_trace.c.payment_id == payment_id)
        ).mappings().all()
        last_run = conn.execute(
            select(t.pipeline_runs.c.finished_at, t.pipeline_runs.c.next_batch_at)
            .order_by(t.pipeline_runs.c.finished_at.desc(), t.pipeline_runs.c.id.desc())
            .limit(1)
        ).mappings().first()
    reached = {r["stage"]: r["at"] for r in rows}
    if pay["executed_at"] is not None:
        reached["ledger"] = pay["executed_at"]
    iso = lambda v: v.isoformat() if v is not None else None  # noqa: E731
    return {
        "payment_id": pay["id"],
        "status": pay["status"],
        "stages": [{"stage": s, "at": iso(reached[s])} for s in TRACE_STAGES if s in reached],
        "last_batch_at": iso(last_run["finished_at"]) if last_run else None,
        "next_batch_at": iso(last_run["next_batch_at"]) if last_run else None,
    }
