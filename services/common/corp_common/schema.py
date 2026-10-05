"""Apply the SQL files in db/ to an engine, translating the T-SQL for SQLite."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine

_GO = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def split_batches(sql: str) -> list[str]:
    return [b.strip() for b in _GO.split(sql) if b.strip()]


def to_sqlite(batch: str) -> str:
    s = batch
    s = re.sub(r"BIGINT\s+IDENTITY\(1,1\)\s+NOT NULL\s+PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", s)
    s = re.sub(r"NVARCHAR\(MAX\)", "TEXT", s)
    s = re.sub(r"REFERENCES\s+\w+\.(\w+)", r"REFERENCES \1", s)
    s = re.sub(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(\w+)\.(\w+)", r"CREATE \1INDEX \3.\2 ON \4", s)
    return s


def apply_sql_file(engine: Engine, path: str | Path) -> None:
    sql = Path(path).read_text()
    batches = split_batches(sql)
    if engine.dialect.name == "sqlite":
        raw = engine.raw_connection()
        try:
            for batch in batches:
                if "-- mssql-only" in batch:
                    continue
                raw.driver_connection.executescript(to_sqlite(batch))
        finally:
            raw.close()
        return
    with engine.begin() as conn:
        for batch in batches:
            conn.exec_driver_sql(batch)
