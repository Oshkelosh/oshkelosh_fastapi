"""Per-request storefront static file handler."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.types import Receive, Scope, Send

from app.services.storefront_resolver import resolve_static_directory

_UNAVAILABLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Storefront unavailable</title></head>
<body><h1>Storefront unavailable</h1><p>No storefront frontend is enabled.</p></body>
</html>
"""


class DynamicStorefrontStatic:
    """ASGI app: resolve frontend per request, delegate to cached StaticFiles."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self._handlers: dict[str, StaticFiles] = {}

    def _get_handler(self, directory: str) -> StaticFiles:
        if directory not in self._handlers:
            self._handlers[directory] = StaticFiles(
                directory=directory,
                html=True,
                check_dir=False,
            )
        return self._handlers[directory]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return

        request = Request(scope, receive)
        directory = resolve_static_directory(request)
        if directory is None:
            response: Response = HTMLResponse(
                content=_UNAVAILABLE_HTML,
                status_code=503,
            )
            await response(scope, receive, send)
            return

        handler = self._get_handler(str(directory))
        await handler(scope, receive, send)


def register_storefront_handler(app: FastAPI) -> None:
    """Mount the dynamic storefront handler at ``/`` (catch-all for unmatched routes)."""
    app.mount("/", DynamicStorefrontStatic(app), name="spa")
