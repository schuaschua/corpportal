"""Cash forecast (CAP-7): 30 days of daily projected non-Reserve balance per company, with an
80% band.

Model (WeekdayCashFlowModel, a scikit-learn estimator logged to MLflow): per company and
weekday, the typical daily net flow learned from gold.daily_flows, as a mean and standard
deviation for two streams:
  other     customer receipts, fees and anything else nobody schedules
  supplier  supplier payments (the run-rate, used only beyond the known schedule)
Payroll and transfers are not learned: payroll is known, and transfers between non-Reserve
accounts net to zero while Reserve moves are treasury decisions.

Projection (project): start from the company's current non-Reserve balance (gold), then day
by day add the learned `other` flow, the learned supplier run-rate only after the last known
scheduled supplier payment, and subtract the known scheduled_payments and payroll on their
dates (payroll repeats on its 28-day WPS cycle inside the horizon). The band widens with the
horizon: +/- z(0.9) x sqrt(sum of the daily variances so far).

So approving a large payment moves the start balance, and the next scoring run's whole path
moves with it; retraining isn't needed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator

NAME = "cash_forecast"
HORIZON_DAYS = 30
BAND = 0.80
Z_BAND = 1.2815515655446004  # standard normal quantile 0.90: a two-sided 80% band
PAYROLL_CYCLE_DAYS = 28
HOLDOUT_DAYS = 28
CENT = Decimal("0.01")
OUTPUT_COLUMNS = ["other_mean", "other_sd", "supplier_mean", "supplier_sd"]


class WeekdayCashFlowModel(BaseEstimator):
    """Typical daily net flow of non-Reserve cash by (company, weekday): mean and SD of the
    unscheduled `other` stream and of the supplier stream."""

    def fit(self, X: pd.DataFrame, y=None):
        """X: features.daily_flow_history (company_id, weekday, other_net, supplier_net, ...)."""
        g = X.groupby(["company_id", "weekday"])
        prof = g.agg(
            other_mean=("other_net", "mean"), other_sd=("other_net", "std"),
            supplier_mean=("supplier_net", "mean"), supplier_sd=("supplier_net", "std"),
            days=("other_net", "size"),
        ).reset_index()
        prof[["other_sd", "supplier_sd"]] = prof[["other_sd", "supplier_sd"]].fillna(0.0)
        prof["company_id"] = prof["company_id"].astype(int)
        prof["weekday"] = prof["weekday"].astype(int)
        self.profile_ = prof
        self.n_days_ = int(len(X))
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """X: (company_id, weekday) -> OUTPUT_COLUMNS; an unknown company or weekday gets zeros."""
        key = pd.DataFrame({"company_id": X["company_id"].astype(int).values, "weekday": X["weekday"].astype(int).values})
        out = key.merge(self.profile_, on=["company_id", "weekday"], how="left")
        return out[OUTPUT_COLUMNS].fillna(0.0).astype(float).reset_index(drop=True)


def _money(x: float) -> Decimal:
    return Decimal(repr(round(float(x), 2))).quantize(CENT)


def project(model: WeekdayCashFlowModel, company_id: int, as_of: date, start_balance: Decimal,
            scheduled: Iterable[tuple[str, Decimal, date]], horizon: int = HORIZON_DAYS) -> list[dict]:
    """The daily path for one company. scheduled: (kind, amount, due_date) of that company.
    Returns [{forecast_date, predicted_balance, lower_bound, upper_bound}] (end-of-day balances)."""
    days = [as_of + timedelta(days=k) for k in range(horizon)]
    end = days[-1]
    supplier_known, payroll = defaultdict(float), defaultdict(float)
    for kind, amount, due in scheduled:
        if due < as_of or due > end:
            continue
        if kind == "payroll":
            payroll[due] += float(amount)
        else:
            supplier_known[due] += float(amount)
    for due, amount in sorted(payroll.items()):
        nxt = due + timedelta(days=PAYROLL_CYCLE_DAYS)
        while nxt <= end:
            payroll.setdefault(nxt, amount)
            nxt += timedelta(days=PAYROLL_CYCLE_DAYS)
    supplier_until = max(supplier_known) if supplier_known else as_of - timedelta(days=1)

    learned = model.predict(pd.DataFrame({"company_id": company_id, "weekday": [d.weekday() for d in days]}))
    balance, variance, rows = float(start_balance), 0.0, []
    for d, p in zip(days, learned.itertuples(index=False)):
        flow = p.other_mean
        variance += p.other_sd ** 2
        if d > supplier_until:
            flow += p.supplier_mean
            variance += p.supplier_sd ** 2
        flow -= supplier_known.get(d, 0.0) + payroll.get(d, 0.0)
        balance += flow
        half = Z_BAND * math.sqrt(variance)
        rows.append({
            "forecast_date": d,
            "predicted_balance": _money(balance),
            "lower_bound": _money(balance - half),
            "upper_bound": _money(balance + half),
        })
    return rows


def backtest(history: pd.DataFrame, holdout_days: int = HOLDOUT_DAYS) -> dict:
    """Fit on all but the last `holdout_days`, score the learned daily flow (other + supplier)
    on them: MAE, MAE of a no-weekday baseline (the company's plain daily mean), and how often
    the actual day falls inside the 80% band."""
    if history.empty:
        return {}
    cutoff = history["flow_date"].max() - timedelta(days=holdout_days - 1)
    train, test = history[history["flow_date"] < cutoff], history[history["flow_date"] >= cutoff]
    if train.empty or test.empty:
        return {}
    pred = WeekdayCashFlowModel().fit(train).predict(test[["company_id", "weekday"]])
    actual = (test["other_net"] + test["supplier_net"]).to_numpy()
    expected = (pred["other_mean"] + pred["supplier_mean"]).to_numpy()
    sd = np.sqrt(pred["other_sd"] ** 2 + pred["supplier_sd"] ** 2).to_numpy()
    plain = (train["other_net"] + train["supplier_net"]).groupby(train["company_id"]).mean()
    naive = test["company_id"].map(plain).fillna(0.0).to_numpy()
    mae, naive_mae = float(np.mean(np.abs(actual - expected))), float(np.mean(np.abs(actual - naive)))
    return {
        "holdout_days": float(holdout_days),
        "holdout_mae": round(mae, 2),
        "naive_mae": round(naive_mae, 2),
        "mae_skill": round(1 - mae / naive_mae, 4) if naive_mae else 0.0,
        "band80_coverage": round(float(np.mean(np.abs(actual - expected) <= Z_BAND * sd)), 4),
        "companies": float(history["company_id"].nunique()),
        "training_days": float(len(history)),
    }


def train(history: pd.DataFrame) -> tuple[WeekdayCashFlowModel, dict]:
    """Backtest metrics, then the model fitted on the whole history (the one registered)."""
    metrics = backtest(history)
    return WeekdayCashFlowModel().fit(history), metrics
