"""X-Served-From: $REGION on every response, errors included."""

from __future__ import annotations

import os

from fastapi import FastAPI

HEADER = "X-Served-From"


def region() -> str:
    return os.environ.get("REGION", "local")


class RegionHeaderMiddleware:
    """Pure ASGI middleware so it also covers exception responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        value = region().encode()

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-served-from"]
                headers.append((b"x-served-from", value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


def install(app: FastAPI) -> None:
    app.add_middleware(RegionHeaderMiddleware)
