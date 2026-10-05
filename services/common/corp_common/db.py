"""Database engine and company-scoped connections.

The URL comes only from the DB_URL environment variable, e.g.
  mssql+pyodbc://<user>:<password>@<host>:1433/corportal?driver=ODBC+Driver+18+for+SQL+Server
  mssql+pyodbc://@<server>.database.windows.net:1433/corportal?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&Authentication=ActiveDirectoryWorkloadIdentity
  sqlite:///.work/dev.db      (tests / quick local runs)

Authentication=ActiveDirectoryWorkloadIdentity is ours, not an ODBC keyword: it is stripped
from the URL and each new connection gets an Entra token for the pod's AKS workload identity
(ODBC's own ActiveDirectoryMsi does not support workload identity).

On SQL Server every scoped connection sets SESSION_CONTEXT('company_id') so the
row-level security policy in db/rls.sql filters rows. Under SQLite the `ops` and
`serving` schemas are attached database files next to the main file.
"""

from __future__ import annotations

import os
import struct
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url

SCHEMAS = ("ops", "serving")
WORKLOAD_IDENTITY_AUTH = "ActiveDirectoryWorkloadIdentity"
ACCESS_TOKEN_AUTH = "ActiveDirectoryAccessToken"  # SQL_ACCESS_TOKEN env (db-init Job)
SQL_COPT_SS_ACCESS_TOKEN = 1256
SQL_TOKEN_SCOPE = "https://database.windows.net/.default"


def _sqlite_engine(url: str) -> Engine:
    u = make_url(url)
    db_path = u.database
    if not db_path or db_path == ":memory:":
        raise ValueError("SQLite needs a file path so the ops/serving schemas can be attached")
    base = Path(db_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # Let SQLAlchemy drive transactions (see _on_begin) and attach the schemas.
        dbapi_conn.isolation_level = None
        for schema in SCHEMAS:
            path = base.with_name(f"{base.stem}.{schema}{base.suffix or '.db'}")
            dbapi_conn.execute(f"ATTACH DATABASE '{path}' AS {schema}")

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        # Take the write lock up front so concurrent approvals serialise like row locks
        # do on SQL Server instead of failing with SQLITE_BUSY on lock upgrade.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return _sqlite_engine(url)
    u = make_url(url)
    auth = u.query.get("Authentication")
    token_auth = auth in (WORKLOAD_IDENTITY_AUTH, ACCESS_TOKEN_AUTH)
    if token_auth:
        u = u.difference_update_query(["Authentication"])
    engine = create_engine(u, pool_pre_ping=True, fast_executemany=url.startswith("mssql+pyodbc"))
    if auth == WORKLOAD_IDENTITY_AUTH:
        _use_workload_identity_token(engine)
    elif auth == ACCESS_TOKEN_AUTH:
        _use_static_token(engine, os.environ["SQL_ACCESS_TOKEN"])

    @event.listens_for(engine, "checkout")
    def _clear_context(dbapi_conn, _record, _proxy):
        # Pooled connections must never carry a previous caller's company.
        cur = dbapi_conn.cursor()
        cur.execute("EXEC sp_set_session_context @key = N'company_id', @value = NULL")
        cur.close()

    return engine


def _token_attrs(cargs: list, cparams: dict, token: bytes) -> None:
    # With no user in the URL SQLAlchemy adds Trusted_Connection=Yes, which ODBC Driver 18
    # rejects next to an access token (FA005).
    if cargs and isinstance(cargs[0], str):
        cargs[0] = ";".join(p for p in cargs[0].split(";") if not p.lower().startswith("trusted_connection="))
    cparams["attrs_before"] = {SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(token)}s", len(token), token)}


def _use_workload_identity_token(engine: Engine) -> None:
    # AZURE_CLIENT_ID, AZURE_TENANT_ID and AZURE_FEDERATED_TOKEN_FILE come from the AKS
    # workload identity webhook; the credential caches the token until it nears expiry.
    from azure.identity import WorkloadIdentityCredential

    credential = WorkloadIdentityCredential()

    @event.listens_for(engine, "do_connect")
    def _add_token(_dialect, _record, cargs, cparams):
        _token_attrs(cargs, cparams, credential.get_token(SQL_TOKEN_SCOPE).token.encode("utf-16-le"))


def _use_static_token(engine: Engine, token: str) -> None:
    raw = token.encode("utf-16-le")

    @event.listens_for(engine, "do_connect")
    def _add_token(_dialect, _record, cargs, cparams):
        _token_attrs(cargs, cparams, raw)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = os.environ.get("DB_URL")
    if not url:
        raise RuntimeError("DB_URL is not set")
    return create_db_engine(url)


def reset_engine() -> None:
    """Dispose the cached engine (tests switch DB_URL between runs)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


@contextmanager
def company_connection(company_id: int) -> Iterator[Connection]:
    """A transaction scoped to one company. company_id must come from the caller's identity."""
    with get_engine().begin() as conn:
        if conn.dialect.name == "mssql":
            conn.exec_driver_sql(
                "EXEC sp_set_session_context @key = N'company_id', @value = ?", (int(company_id),)
            )
        yield conn


@contextmanager
def system_connection() -> Iterator[Connection]:
    """An unscoped transaction for tables without RLS (users lookup, access log)."""
    with get_engine().begin() as conn:
        yield conn
