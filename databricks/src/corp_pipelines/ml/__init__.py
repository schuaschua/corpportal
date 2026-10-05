"""ML for the Corporate Portal PoC (piece 4: CAP-7 cash forecast, CAP-8 anomaly detection).

features.py  gold frames -> model inputs (pandas)
forecast.py  per-company weekday cash-flow baseline + the 30-day projection with an 80% band
anomaly.py   Isolation Forest over payment features, score in [0, 1] and a plain reason
registry.py  MLflow tracking and registry (file store locally, Unity Catalog on Databricks)
jobs.py      the `train` and `score` tasks

scikit-learn and MLflow only: no deep learning, no LLMs, no serving endpoints; scoring is
batch, after gold, into the SQL serving tables the portal reads through insights-api.
"""
