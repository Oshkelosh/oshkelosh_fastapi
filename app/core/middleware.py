"""
Middleware stack for the Oshkelosh application.

Includes:
- CORS middleware (built-in FastAPI)
- Request-ID tracing middleware
- Exception handler middleware (normalises errors to JSON responses)
"""

import logging
import time
import uuid
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.core.exceptions import AppException
from app.core.setup_middleware import SetupRedirectMiddleware

logger = logging.getLogger("oshkelosh.middleware")


# ------------------------------------------------------------------
# CORS middleware
# ------------------------------------------------------------------
def setup_cors(app: FastAPI) -> None:
    """Configure CORS on the FastAPI application."""
    if settings.app_env == "production":
        allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        allow_headers = [
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
            # Order creation dedupe header — without it cross-origin storefront
            # checkouts fail the CORS preflight in production.
            "Idempotency-Key",
        ]
    else:
        allow_methods = ["*"]
        allow_headers = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )


# ------------------------------------------------------------------
# Request-ID middleware
# ------------------------------------------------------------------
REQUEST_ID_HEADER = "X-Request-ID"


def _get_request_id(request: Request) -> str:
    """Extract a request ID from the header, or generate a new one."""
    return request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject a unique request ID into each request/response cycle."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = _get_request_id(request)
        request.state.request_id = request_id  # type: ignore[attr-defined]

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


# ------------------------------------------------------------------
# Exception handler middleware
# ------------------------------------------------------------------
class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return structured JSON error responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            response = await call_next(request)
        except AppException as exc:
            headers = {REQUEST_ID_HEADER: getattr(request.state, "request_id", "")}
            from app.core.exceptions import RateLimitExceeded

            if isinstance(exc, RateLimitExceeded) and exc.retry_after is not None:
                headers["Retry-After"] = str(exc.retry_after)
            response = JSONResponse(
                status_code=exc.status_code,
                content=exc.to_dict(),
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            request_id = getattr(request.state, "request_id", "")
            logger.exception(
                "Unhandled exception during %s %s",
                request.method,
                request.url.path,
                extra={"request_id": request_id},
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "An unexpected error occurred",
                },
                headers={REQUEST_ID_HEADER: request_id},
            )
        return response


# ------------------------------------------------------------------
# Timing / logging middleware
# ------------------------------------------------------------------
class TimingMiddleware(BaseHTTPMiddleware):
    """Log request duration for observability."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        request_id = getattr(request.state, "request_id", "")
        logger.info(
            "%s %s -> %d (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={"request_id": request_id},
        )
        return response


# ------------------------------------------------------------------
# Registry – call this once during app startup
# ------------------------------------------------------------------
def register_middleware(app: FastAPI) -> None:
    """Apply all middleware layers to the FastAPI app."""
    setup_cors(app)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(ExceptionHandlerMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(SetupRedirectMiddleware)
