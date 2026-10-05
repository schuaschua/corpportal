"""Payment anomaly detection (CAP-8): an Isolation Forest over gold.payment_features.

Model (PaymentAnomalyModel, a scikit-learn estimator logged to MLflow): an IsolationForest
on features.ANOMALY_FEATURES. Every tree sees every payment (max_samples=1.0): the rare
patterns we care about (one duplicate, one night-time payment) are single rows, and a
subsample would leave them out of most trees. Score = the Isolation Forest anomaly score
2^(-E[h(x)]/c(n)) in [0, 1] (sklearn's -score_samples); a payment is flagged at or above
THRESHOLD. Deterministic for a given random_state.

Reason: one plain line naming the payment's strongest feature, the one whose value is rarest
in the training data (the smallest share of payments at least as extreme), e.g.
"Unusual: 4× this supplier's average". Flags inform; they never block a payment.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import IsolationForest

from .features import ANOMALY_FEATURES

NAME = "payment_anomaly"
THRESHOLD = 0.65
N_ESTIMATORS = 300
GST = timedelta(hours=4)
# Tie-break when two features are equally rare: the more specific explanation first.
PRIORITY = ["dup_count", "log_ratio", "hour_gst", "is_weekend", "is_first_time", "log_amount_rel"]


class PaymentAnomalyModel(BaseEstimator):
    def __init__(self, n_estimators: int = N_ESTIMATORS, threshold: float = THRESHOLD, random_state: int = 42):
        self.n_estimators = n_estimators
        self.threshold = threshold
        self.random_state = random_state

    def fit(self, X: pd.DataFrame, y=None):
        X = X[ANOMALY_FEATURES].astype(float)
        self.forest_ = IsolationForest(
            n_estimators=self.n_estimators, max_samples=1.0, random_state=self.random_state
        ).fit(X.to_numpy())
        self.hour_median_ = float(np.median(X["hour_gst"]))
        self.reference_ = {f: np.sort(self._extremity(X, f)) for f in ANOMALY_FEATURES}
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Anomaly score in [0, 1] per payment."""
        return -self.forest_.score_samples(X[ANOMALY_FEATURES].astype(float).to_numpy())

    def _extremity(self, X: pd.DataFrame, feature: str) -> np.ndarray:
        v = X[feature].astype(float).to_numpy()
        if feature in ("log_ratio", "log_amount_rel"):
            return np.abs(v)
        if feature == "hour_gst":
            return np.abs(v - self.hour_median_)
        return v  # flags and counts: higher is rarer

    def rarity(self, X: pd.DataFrame) -> pd.DataFrame:
        """Share of training payments at least as extreme, per feature (1.0 = not unusual)."""
        out = {}
        for f in ANOMALY_FEATURES:
            ref, e = self.reference_[f], self._extremity(X, f)
            share = 1.0 - np.searchsorted(ref, e, side="left") / len(ref)
            out[f] = np.where(e > 0, share, 1.0)
        return pd.DataFrame(out, index=X.index)

    def strongest(self, X: pd.DataFrame) -> list[str]:
        r = self.rarity(X)
        return [min(PRIORITY, key=lambda f: (row[f], PRIORITY.index(f))) for _, row in r.iterrows()]


def _times(x: float) -> str:
    return f"{x:.0f}" if x >= 10 else f"{x:.1f}".rstrip("0").rstrip(".")


def reason(row, feature: str) -> str:
    """One plain line for a flagged payment. row: an anomaly_frame row."""
    local = pd.Timestamp(row["executed_at"]).to_pydatetime() + GST
    when = f"{local:%A %H:%M}"
    if feature == "dup_count":
        payee = "account" if row["counterparty"] == "Own account transfer" else "supplier"
        return f"Possible duplicate: same {payee}, amount and day as an earlier payment"
    if feature == "log_ratio" and pd.notna(row["ratio"]):
        return f"Unusual: {_times(row['ratio'])}× this supplier's average"
    if feature in ("hour_gst", "is_weekend"):
        tail = " to a first-time beneficiary" if row["is_first_time"] else ""
        return f"Unusual: {when} payment{tail}"
    if feature == "is_first_time":
        return "Unusual: first payment to this beneficiary"
    rel = float(np.exp(row["log_amount_rel"]))
    return f"Unusual: {_times(rel)}× this company's typical payment"


def train(frame: pd.DataFrame, seed: int) -> tuple[PaymentAnomalyModel, dict]:
    model = PaymentAnomalyModel(random_state=seed).fit(frame)
    scores = model.predict(frame)
    flagged = int((scores >= model.threshold).sum())
    return model, {
        "payments": float(len(frame)),
        "flagged": float(flagged),
        "flag_rate": round(flagged / len(frame), 4) if len(frame) else 0.0,
        "score_p50": round(float(np.median(scores)), 4) if len(frame) else 0.0,
        "score_max": round(float(scores.max()), 4) if len(frame) else 0.0,
    }


def flag(model: PaymentAnomalyModel, frame: pd.DataFrame) -> pd.DataFrame:
    """The flagged payments with score and reason, ordered by payment id."""
    if frame.empty:
        return frame.assign(score=[], reason=[])
    scores = model.predict(frame)
    hit = frame[scores >= model.threshold].copy()
    hit["score"] = scores[scores >= model.threshold]
    hit["reason"] = [reason(r, f) for (_, r), f in zip(hit.iterrows(), model.strongest(hit))]
    return hit
