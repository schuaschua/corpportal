"""MLflow tracking and model registry, the same calls locally and on Databricks.

Local       tracking and registry: an MLflow file store in the `lake` volume
            (MLFLOW_TRACKING_URI, default <LAKE_DIR>/../mlruns, i.e. /lake/mlruns in compose).
Databricks  tracking: the workspace; registry: Unity Catalog (databricks-uc).

Registered names are <catalog>.ml.<model> (corportal.ml.cash_forecast,
corportal.ml.payment_anomaly) in both places. Each training run logs params, metrics and the
fitted scikit-learn estimator, registers a new version and points the `champion` alias at
it; scoring loads models:/<name>@champion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("corp_pipelines.ml")

ALIAS = "champion"
PIP_REQUIREMENTS = ["scikit-learn>=1.3", "pandas>=1.5", "numpy>=1.23", "corp-pipelines"]


@dataclass(frozen=True)
class Registered:
    name: str             # short name: cash_forecast | payment_anomaly
    registered_name: str  # <catalog>.ml.<name>
    version: str
    run_id: str | None


def registered_name(settings, name: str) -> str:
    return f"{settings.catalog}.ml.{name}"


def configure(settings) -> None:
    import mlflow

    if settings.local:
        uri = settings.mlflow_tracking_uri or (Path(settings.lake_dir).resolve().parent / "mlruns").as_uri()
        mlflow.set_tracking_uri(uri)
        mlflow.set_registry_uri(uri)
        experiment = settings.mlflow_experiment or "corportal-ml"
    else:
        mlflow.set_tracking_uri("databricks")
        mlflow.set_registry_uri("databricks-uc")
        experiment = settings.mlflow_experiment or "/Shared/corportal-ml"
    mlflow.set_experiment(experiment)


def log_and_register(settings, name: str, model, example_X, params: dict, metrics: dict) -> Registered:
    """One MLflow run: params, metrics, the model (with its signature, which Unity Catalog
    requires); then a new registered version, aliased `champion`."""
    import mlflow
    import mlflow.sklearn
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient

    full = registered_name(settings, name)
    signature = infer_signature(example_X, model.predict(example_X))
    artifact = {"name": "model"} if int(mlflow.__version__.split(".")[0]) >= 3 else {"artifact_path": "model"}
    with mlflow.start_run(run_name=f"{name}-train") as run:
        mlflow.set_tags({"corportal.model": name, "corportal.data": "synthetic"})
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(
            model, signature=signature, registered_model_name=full, pip_requirements=PIP_REQUIREMENTS, **artifact
        )
    client = MlflowClient()
    versions = [v for v in client.search_model_versions(f"name='{full}'") if v.run_id == run.info.run_id]
    version = str(max(int(v.version) for v in versions))
    client.set_registered_model_alias(full, ALIAS, version)
    log.info("registered %s v%s (run %s)", full, version, run.info.run_id)
    return Registered(name, full, version, run.info.run_id)


def load_champion(settings, name: str):
    """(model, Registered) for the `champion` version, or None when nothing is registered yet."""
    import mlflow.sklearn
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    full = registered_name(settings, name)
    try:
        mv = MlflowClient().get_model_version_by_alias(full, ALIAS)
    except MlflowException as exc:
        log.info("no %s@%s in the registry yet (%s)", full, ALIAS, str(exc).splitlines()[0][:160])
        return None
    model = mlflow.sklearn.load_model(f"models:/{full}/{mv.version}")
    return model, Registered(name, full, str(mv.version), mv.run_id)
