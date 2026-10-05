"""Test fixtures: a fresh SQLite database per test, built from db/schema.sql and the generator."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 10, 5)  # a Monday, like the demo
sys.path.insert(0, str(ROOT / "databricks" / "src"))  # corp_pipelines (Spark only where used)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


generator = _load("generate", ROOT / "data" / "generator" / "generate.py")
accounts_api = _load("accounts_api", ROOT / "services" / "accounts-api" / "app.py")
payments_api = _load("payments_api", ROOT / "services" / "payments-api" / "app.py")
insights_api = _load("insights_api", ROOT / "services" / "insights-api" / "app.py")
outbox_relay = _load("outbox_relay", ROOT / "services" / "outbox-relay" / "app.py")


@lru_cache(maxsize=None)
def dataset(seed: int = 42, as_of: date = AS_OF) -> dict:
    return generator.generate(seed, as_of)


@pytest.fixture
def db(tmp_path, monkeypatch):
    from corp_common.db import get_engine, reset_engine
    from corp_common.schema import apply_sql_file

    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path / 'corportal.db'}")
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.delenv("REGION", raising=False)
    reset_engine()
    engine = get_engine()
    apply_sql_file(engine, ROOT / "db" / "schema.sql")
    generator.load(engine, dataset())
    yield engine
    reset_engine()


@pytest.fixture(scope="module")
def spark():
    """A local SparkSession per Spark test module, stopped at its end."""
    from corp_pipelines.lake import local_spark

    s = local_spark("corp-pipelines-tests")
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


@pytest.fixture
def accounts(db):
    return TestClient(accounts_api.app)


@pytest.fixture
def payments(db):
    return TestClient(payments_api.app)


@pytest.fixture
def insights(db):
    return TestClient(insights_api.app)


def as_user(username: str) -> dict:
    return {"X-Demo-User": username}
