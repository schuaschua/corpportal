"""insights-api: the ML results for the caller's company (CAP-7 cash forecast, CAP-8 anomalies).

Reads only the SQL serving tables the batch scoring writes (serving.forecast,
serving.anomalies) and the registered-model summary the training writes (serving.models).
No model is loaded here: scoring is batch, in the lake pipeline. Company scoping, the
region header and deny-by-404 come from corp_common, as in the other services.
"""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import Depends, Query
from sqlalchemy import and_, select

from corp_common import tables as t
from corp_common.app_factory import create_app
from corp_common.auth import User, current_user
from corp_common.db import company_connection
from corp_common.scoping import Denied, money, utcnow

app = create_app("insights-api")


def _iso(v):
    return v.isoformat() if v is not None else None


def _anomaly(a) -> dict:
    return {
        "id": a["id"],
        "payment_id": a["payment_id"],
        "transaction_id": a["transaction_id"],
        "occurred_at": _iso(a["occurred_at"]),
        "counterparty": a["counterparty"],
        "amount": money(a["amount"]),
        "score": str(a["score"]),
        "reason": a["reason"],
        "detected_at": _iso(a["detected_at"]),
        "model": {"name": a["model_name"], "version": a["model_version"]},
    }


@app.get("/forecast")
def forecast(user: User = Depends(current_user)):
    """The 30-day cash forecast (non-Reserve cash) from serving.forecast, with its model."""
    cid = user.company_id
    with company_connection(cid) as conn:
        rows = conn.execute(
            select(t.forecast)
            .where(t.forecast.c.company_id == cid)
            .order_by(t.forecast.c.forecast_date)
            .limit(30)
        ).mappings().all()
    first = rows[0] if rows else None
    return {
        "company": {"id": cid, "name": user.company_name},
        "currency": "AED",
        "model": {"name": first["model_name"], "version": first["model_version"]} if first else None,
        "generated_at": _iso(first["generated_at"]) if first else None,
        "points": [
            {
                "date": r["forecast_date"].isoformat(),
                "predicted": money(r["predicted_balance"]),
                "lower": money(r["lower_bound"]),
                "upper": money(r["upper_bound"]),
            }
            for r in rows
        ],
    }


@app.get("/anomalies")
def anomalies(days: int | None = Query(None, ge=1, le=366), user: User = Depends(current_user)):
    """The caller's flagged payments, newest first. Flags inform; they never block a payment."""
    cid = user.company_id
    q = select(t.anomalies).where(t.anomalies.c.company_id == cid)
    if days:
        q = q.where(t.anomalies.c.occurred_at >= utcnow() - timedelta(days=days))
    with company_connection(cid) as conn:
        rows = conn.execute(q.order_by(t.anomalies.c.occurred_at.desc(), t.anomalies.c.id.desc())).mappings().all()
    return {"company": {"id": cid, "name": user.company_name}, "anomalies": [_anomaly(a) for a in rows]}


@app.get("/anomalies/{payment_id}")
def payment_anomaly(payment_id: int, user: User = Depends(current_user)):
    """Whether one of the caller's payments is flagged. Another company's payment is a 404
    with an access_denied audit row."""
    cid = user.company_id
    with company_connection(cid) as conn:
        owned = conn.execute(
            select(t.payments.c.id).where(and_(t.payments.c.id == payment_id, t.payments.c.company_id == cid))
        ).first()
        if owned is None:
            raise Denied(user, "payment", payment_id)
        row = conn.execute(
            select(t.anomalies).where(and_(t.anomalies.c.payment_id == payment_id, t.anomalies.c.company_id == cid))
        ).mappings().first()
    return {"payment_id": payment_id, "flagged": row is not None, "anomaly": _anomaly(row) if row else None}


@app.get("/models")
def models(user: User = Depends(current_user)):
    """The registered models behind the figures: name, version, trained_at and metrics."""
    with company_connection(user.company_id) as conn:
        rows = conn.execute(select(t.models).order_by(t.models.c.model_name)).mappings().all()
    return {
        "models": [
            {
                "name": r["model_name"],
                "registered_name": r["registered_name"],
                "version": r["model_version"],
                "trained_at": _iso(r["trained_at"]),
                "metrics": json.loads(r["metrics"]),
                "run_id": r["run_id"],
            }
            for r in rows
        ]
    }
