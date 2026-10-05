"""The two ML tasks: train (manual or daily) and score (every batch, after gold).

train  gold -> fit the cash forecast and the Isolation Forest -> MLflow run + new registered
       versions (alias `champion`) -> serving.models (name, version, trained_at, metrics).
score  champion models + gold -> serving.forecast (30 days per company) and
       serving.anomalies (flagged payments with score and reason), replaced in one
       transaction; every row names its model and version. Skipped, leaving serving as it
       is, when no model is registered yet, and when nothing moved since the last scoring
       with the same model versions and business date.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from decimal import Decimal

import pandas as pd
from pyspark.sql import functions as F

from .. import silver
from ..lake import Lake, utcnow
from . import anomaly, features, forecast, registry

log = logging.getLogger("corp_pipelines.ml")

PAYMENT_FEATURE_COLUMNS = [
    "payment_id", "company_id", "transaction_id", "counterparty", "amount", "executed_at", "hour_gst",
    "is_weekend", "is_first_time_beneficiary", "same_day_duplicates", "amount_to_prior_mean",
]


def _flow_history(lake: Lake) -> pd.DataFrame:
    flows = features.to_pandas(lake.read("gold", "daily_flows").select("company_id", "flow_date", *features.FLOW_COLUMNS))
    return features.daily_flow_history(flows, lake.settings.business_date())


def _payment_frame(lake: Lake) -> pd.DataFrame:
    if not lake.exists("gold", "payment_features"):
        return pd.DataFrame(columns=PAYMENT_FEATURE_COLUMNS)
    return features.anomaly_frame(features.to_pandas(lake.read("gold", "payment_features").select(*PAYMENT_FEATURE_COLUMNS)))


def train(spark, lake: Lake, store, run_id: str) -> dict:
    s = lake.settings
    if not (lake.exists("gold", "daily_flows") and lake.exists("gold", "payment_features")):
        log.warning("train skipped: gold has no flows or payment features yet (run the backfill first)")
        return {"status": "skipped", "reason": "no gold data"}
    history, frame = _flow_history(lake), _payment_frame(lake)
    if history.empty or frame.empty:
        log.warning("train skipped: no history before %s", s.business_date())
        return {"status": "skipped", "reason": "no history"}

    fc_model, fc_metrics = forecast.train(history)
    an_model, an_metrics = anomaly.train(frame, s.ml_seed)

    registry.configure(s)
    fc = registry.log_and_register(
        s, forecast.NAME, fc_model, history[["company_id", "weekday"]].head(14),
        {"horizon_days": forecast.HORIZON_DAYS, "band": forecast.BAND, "baseline": "mean daily net flow by company and weekday",
         "streams": "other, supplier", "payroll_cycle_days": forecast.PAYROLL_CYCLE_DAYS,
         "history_from": str(history["flow_date"].min()), "history_to": str(history["flow_date"].max()),
         "pipeline_run_id": run_id},
        fc_metrics,
    )
    an = registry.log_and_register(
        s, anomaly.NAME, an_model, frame[features.ANOMALY_FEATURES].head(14),
        {"algorithm": "IsolationForest", "n_estimators": an_model.n_estimators, "max_samples": 1.0,
         "threshold": an_model.threshold, "random_state": an_model.random_state,
         "features": ",".join(features.ANOMALY_FEATURES), "pipeline_run_id": run_id},
        an_metrics,
    )
    trained_at = utcnow()
    store.write_models([
        {"model_name": r.name, "registered_name": r.registered_name, "model_version": r.version,
         "trained_at": trained_at, "metrics": json.dumps(m, sort_keys=True), "run_id": r.run_id}
        for r, m in ((fc, fc_metrics), (an, an_metrics))
    ])
    result = {"status": "trained", forecast.NAME: fc.version, anomaly.NAME: an.version}
    log.info("train %s: %s", run_id, result)
    return result


def _start_balances(lake: Lake) -> dict[int, Decimal]:
    """Current non-Reserve balance per company: the latest gold.cash_position_daily date."""
    cash = lake.read("gold", "cash_position_daily")
    latest = cash.agg(F.max("position_date")).first()[0]
    rows = (
        cash.where((F.col("position_date") == F.lit(latest)) & (F.col("account_kind") != "reserve"))
        .groupBy("company_id").agg(F.sum("balance").alias("balance")).collect()
    )
    return {int(r["company_id"]): Decimal(str(r["balance"])) for r in rows}


def forecast_rows(model, reg: registry.Registered, balances: dict[int, Decimal], scheduled, as_of, now) -> list[dict]:
    by_company = defaultdict(list)
    for cid, kind, amount, due in scheduled:
        by_company[int(cid)].append((kind, amount, due))
    out = []
    for cid in sorted(balances):
        for r in forecast.project(model, cid, as_of, balances[cid], by_company[cid]):
            out.append({"company_id": cid, **r, "model_name": reg.name, "model_version": reg.version, "generated_at": now})
    return out


def anomaly_rows(model, reg: registry.Registered, frame: pd.DataFrame, now) -> list[dict]:
    hits = anomaly.flag(model, frame).sort_values(["company_id", "executed_at", "payment_id"])
    out = []
    for i, (_, r) in enumerate(hits.iterrows(), start=1):
        out.append({
            "id": i,
            "company_id": int(r["company_id"]),
            "payment_id": int(r["payment_id"]),
            "transaction_id": None if pd.isna(r["transaction_id"]) else int(r["transaction_id"]),
            "occurred_at": pd.Timestamp(r["executed_at"]).to_pydatetime(),
            "counterparty": str(r["counterparty"]),
            "amount": Decimal(str(r["amount"])).quantize(Decimal("0.01")),
            "score": Decimal(f"{min(max(float(r['score']), 0.0), 1.0):.4f}"),
            "reason": r["reason"],
            "detected_at": now,
            "model_name": reg.name,
            "model_version": reg.version,
        })
    return out


def score(spark, lake: Lake, store, run_id: str | None = None) -> dict:
    s = lake.settings
    registry.configure(s)
    fc, an = registry.load_champion(s, forecast.NAME), registry.load_champion(s, anomaly.NAME)
    if fc is None or an is None:
        log.warning("score skipped: no trained model yet (run train); serving left unchanged")
        return {"status": "skipped", "reason": "no model"}
    if not lake.exists("gold", "cash_position_daily"):
        log.warning("score skipped: no gold yet; serving left unchanged")
        return {"status": "skipped", "reason": "no gold data"}
    (fc_model, fc_reg), (an_model, an_reg) = fc, an
    as_of = s.business_date()
    moved = bool(run_id) and silver.new_rows(lake, run_id).limit(1).count() > 0
    state = store.read_scoring_state()
    if (not moved and state["forecast"] == {(fc_reg.name, fc_reg.version, as_of)}
            and state["anomalies"] <= {(an_reg.name, an_reg.version)}):
        return {"status": "unchanged"}

    now = utcnow()
    frows = forecast_rows(fc_model, fc_reg, _start_balances(lake), store.read_scheduled(), as_of, now)
    arows = anomaly_rows(an_model, an_reg, _payment_frame(lake), now)
    store.replace_scores(frows, arows)
    result = {"status": "scored", "forecast_rows": len(frows), "anomalies": len(arows),
              forecast.NAME: fc_reg.version, anomaly.NAME: an_reg.version}
    log.info("score %s: %s", run_id, result)
    return result
