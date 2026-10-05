"""Model inputs from gold, as pandas frames (the data is small: one row per company-day and
one row per executed payment).

Forecast   gold.daily_flows -> one row per company per Gulf day before the business date,
           missing days filled with zero flows (a quiet weekend is information too).
Anomaly    gold.payment_features -> the Isolation Forest's feature matrix.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

FLOW_COLUMNS = ("other_net", "supplier_net", "payroll_net", "transfer_net")

# Isolation Forest features, all scale-free per company or beneficiary:
ANOMALY_FEATURES = [
    "log_amount_rel",   # log(amount / the company's median payment)
    "log_ratio",        # log(amount / this beneficiary's mean so far); 0 for a first payment
    "hour_gst",         # Gulf hour of execution
    "is_weekend",       # Saturday or Sunday, Gulf time
    "is_first_time",    # first payment to a beneficiary, with enough history to know
    "dup_count",        # earlier same-day payments, same beneficiary, same amount
]


def to_pandas(df) -> pd.DataFrame:
    """A small Spark frame as pandas, via collect (DataFrame.toPandas on PySpark 3.5 imports
    distutils, which Python 3.12 no longer has)."""
    return pd.DataFrame([tuple(r) for r in df.collect()], columns=df.columns)


def daily_flow_history(flows: pd.DataFrame, until: date) -> pd.DataFrame:
    """Complete daily history per company, first flow day .. until - 1 (whole days only).

    flows: gold.daily_flows as pandas (company_id, flow_date, *FLOW_COLUMNS)."""
    cols = ["company_id", "flow_date", "weekday", *FLOW_COLUMNS]
    if flows.empty:
        return pd.DataFrame(columns=cols)
    df = flows.copy()
    df["flow_date"] = pd.to_datetime(df["flow_date"]).dt.date
    for c in FLOW_COLUMNS:
        df[c] = df[c].astype(float)
    df = df[df["flow_date"] < until]
    frames = []
    for cid, g in df.groupby("company_id", sort=True):
        start = g["flow_date"].min()
        days = [start + timedelta(days=i) for i in range((until - start).days)]
        full = pd.DataFrame({"flow_date": days})
        full = full.merge(g[["flow_date", *FLOW_COLUMNS]], on="flow_date", how="left").fillna(0.0)
        full.insert(0, "company_id", int(cid))
        frames.append(full)
    if not frames:
        return pd.DataFrame(columns=cols)
    out = pd.concat(frames, ignore_index=True)
    out["weekday"] = [d.weekday() for d in out["flow_date"]]  # Monday = 0
    return out[cols].sort_values(["company_id", "flow_date"]).reset_index(drop=True)


def anomaly_frame(features: pd.DataFrame) -> pd.DataFrame:
    """gold.payment_features (pandas) -> payments sorted by id with ANOMALY_FEATURES added."""
    df = features.sort_values("payment_id").reset_index(drop=True).copy()
    amount = df["amount"].astype(float)
    median = amount.groupby(df["company_id"]).transform("median")
    ratio = pd.to_numeric(df["amount_to_prior_mean"], errors="coerce").astype(float)
    df["amount_f"] = amount
    df["ratio"] = ratio
    df["log_amount_rel"] = np.log(amount / median)
    df["log_ratio"] = np.log(ratio.fillna(1.0).clip(lower=1e-6))
    df["hour_gst"] = df["hour_gst"].astype(int)
    df["is_weekend"] = df["is_weekend"].astype(bool).astype(int)
    df["is_first_time"] = df["is_first_time_beneficiary"].fillna(False).astype(bool).astype(int)
    df["dup_count"] = df["same_day_duplicates"].fillna(0).astype(int)
    return df
