"""insights-api (microservice #4): forecast, anomalies and models from the serving tables."""

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from conftest import AS_OF, as_user, dataset
from corp_common import tables as t


def test_forecast_is_30_days_scoped_to_callers_company(insights):
    nw = insights.get("/forecast", headers=as_user("priya"))
    fb = insights.get("/forecast", headers=as_user("omar")).json()
    assert nw.status_code == 200 and nw.headers["X-Served-From"] == "local"
    body = nw.json()
    assert body["company"]["name"] == "Northwind Logistics LLC"
    assert body["model"] == {"name": "cash-forecast-baseline", "version": "seed-0"}
    assert len(body["points"]) == 30 and body["points"][0]["date"] == AS_OF.isoformat()
    assert all(Decimal(p["lower"]) <= Decimal(p["predicted"]) <= Decimal(p["upper"]) for p in body["points"])
    assert fb["company"]["name"] != body["company"]["name"] and fb["points"] != body["points"]


def test_anomalies_are_scoped_to_the_caller_and_other_payments_denied(insights, db):
    spike = next(a for a in dataset()["anomalies"] if a["counterparty"] == "Harbour Freight Co")
    nw = insights.get("/anomalies", headers=as_user("priya")).json()["anomalies"]
    assert [a["counterparty"] for a in nw] == ["Harbour Freight Co"]
    assert nw[0]["model"] == {"name": "payment-anomaly-baseline", "version": "seed-0"}
    mine = insights.get(f"/anomalies/{spike['payment_id']}", headers=as_user("tom")).json()
    assert mine["flagged"] and mine["anomaly"]["reason"] == "Unusual: 4× this supplier's average"

    omar = insights.get("/anomalies", headers=as_user("omar"))
    assert omar.status_code == 200 and omar.json()["company"]["name"] == "Fabrikam Trading LLC"
    assert all(a["counterparty"] != "Harbour Freight Co" for a in omar.json()["anomalies"])
    denied = insights.get(f"/anomalies/{spike['payment_id']}", headers=as_user("omar"))
    assert denied.status_code == 404 and denied.headers["X-Served-From"] == "local"
    with db.connect() as conn:
        log = conn.execute(select(t.access_log)).mappings().all()
    assert [(e["username"], e["action"], e["target_type"], e["target_id"]) for e in log] == [
        ("omar", "access_denied", "payment", str(spike["payment_id"]))]


def test_models_lists_name_version_trained_at_and_metrics(insights, db):
    assert insights.get("/models", headers=as_user("priya")).json() == {"models": []}  # before any training
    with db.begin() as conn:
        conn.execute(t.models.insert().values(
            model_name="cash_forecast", registered_name="corportal.ml.cash_forecast", model_version="3",
            trained_at=datetime(2026, 10, 5, 2, 30), metrics=json.dumps({"holdout_mae": 81234.5}), run_id="abc"))
    [m] = insights.get("/models", headers=as_user("omar")).json()["models"]
    assert (m["name"], m["version"], m["trained_at"]) == ("cash_forecast", "3", "2026-10-05T02:30:00")
    assert m["metrics"] == {"holdout_mae": 81234.5} and m["registered_name"] == "corportal.ml.cash_forecast"
