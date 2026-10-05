"""Company scoping helpers: deny-by-404 with an access_denied audit row."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import tables as t
from .auth import User
from .db import system_connection

log = logging.getLogger("corp_common.access")

DENIED_MESSAGE = "You don't have access to that company's data."


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def money(value) -> str | None:
    """DECIMAL(18,2) AED as a fixed-point string; the UI formats it."""
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


class Denied(Exception):
    """Raised when a target is not visible to the caller's company.

    A row outside the caller's company is indistinguishable from a missing row (404), so
    the caller learns nothing about other companies. The handler logs the attempt in its
    own transaction, after the request's scoped transaction has been rolled back.
    """

    def __init__(self, user: User, target_type: str, target_id, detail: str | None = None):
        super().__init__(f"{target_type}:{target_id}")
        self.user, self.target_type, self.target_id, self.detail = user, target_type, str(target_id), detail


def record_denied(exc: Denied) -> None:
    u = exc.user
    log.warning("access_denied user=%s company=%s target=%s:%s", u.username, u.company_id, exc.target_type, exc.target_id)
    with system_connection() as conn:
        conn.execute(
            t.access_log.insert().values(
                occurred_at=utcnow(),
                user_id=u.id,
                username=u.username,
                company_id=u.company_id,
                action="access_denied",
                target_type=exc.target_type,
                target_id=exc.target_id,
                detail=exc.detail,
            )
        )


def install(app: FastAPI) -> None:
    @app.exception_handler(Denied)
    async def _denied(_request: Request, exc: Denied):
        record_denied(exc)
        return JSONResponse({"detail": DENIED_MESSAGE}, status_code=404)
