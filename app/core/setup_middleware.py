"""Redirect browsers to /setup until the first admin user exists."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.config import settings

SETUP_PATH = "/setup"


def _is_exempt_path(path: str) -> bool:
    if path == SETUP_PATH or path.startswith(f"{SETUP_PATH}/"):
        return True
    if path == "/health":
        return True
    if path.startswith("/api/"):
        return True
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    if path.startswith("/media/"):
        return True
    admin_static = f"{settings.admin_prefix}/static/"
    if path.startswith(admin_static):
        return True
    return False


def _should_redirect_to_setup(path: str) -> bool:
  if path == "/":
      return True
  admin = settings.admin_prefix.rstrip("/")
  if path == admin or path.startswith(f"{admin}/"):
      return True
  return False


class SetupRedirectMiddleware(BaseHTTPMiddleware):
    """Gate the app while no admin user exists.

    Browsers are redirected to /setup; the public API is disabled (503) so an
    unconfigured deployment does not expose a live commerce surface.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not getattr(request.app.state, "needs_setup", False):
            return await call_next(request)

        from app.db.connection import session_scope
        from app.services.bootstrap import has_admin_user

        async with session_scope() as session:
            if await has_admin_user(session):
                request.app.state.needs_setup = False
                return await call_next(request)

        path = request.url.path
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=503,
                content={
                    "error": "setup_required",
                    "message": "Store setup is not complete",
                },
            )

        if request.method != "GET":
            return await call_next(request)

        if _is_exempt_path(path) or not _should_redirect_to_setup(path):
            return await call_next(request)

        return RedirectResponse(url=SETUP_PATH, status_code=307)
