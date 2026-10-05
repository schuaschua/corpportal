"""Common FastAPI app setup for every service."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy import text

from . import middleware, scoping
from .db import get_engine


def create_app(title: str) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title=title)
    middleware.install(app)
    scoping.install(app)

    @app.get("/healthz")
    def healthz():
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "region": middleware.region()}

    return app
