"""Rate limiting for sensitive API endpoints."""

from __future__ import annotations

from fastapi import FastAPI, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded as SlowAPIRateLimitExceeded
from starlette.responses import JSONResponse

from app.config import settings
from app.core.exceptions import RateLimitExceeded


def _client_key(request: Request) -> str:
    remote_addr = request.client.host if request.client else None
    trusted_proxies = {ip.strip() for ip in settings.trusted_proxy_ips if ip.strip()}
    if remote_addr and remote_addr in trusted_proxies:
        for header_name in settings.trusted_proxy_headers:
            raw = request.headers.get(header_name)
            if not raw:
                continue
            forwarded = raw.split(",")[0].strip()
            if forwarded:
                return forwarded
    return remote_addr or "unknown"


limiter = Limiter(
    key_func=_client_key,
    enabled=settings.rate_limit_enabled,
    default_limits=[],
)


def register_rate_limiting(app: FastAPI) -> None:
    """Attach limiter state and map slowapi errors to application JSON."""
    app.state.limiter = limiter

    @app.exception_handler(SlowAPIRateLimitExceeded)
    async def _slowapi_rate_limit_handler(
        request: Request, exc: SlowAPIRateLimitExceeded
    ) -> JSONResponse:
        retry_after = getattr(exc, "retry_after", None)
        app_exc = RateLimitExceeded(retry_after=int(retry_after) if retry_after else None)
        headers: dict[str, str] = {}
        if app_exc.retry_after is not None:
            headers["Retry-After"] = str(app_exc.retry_after)
        return JSONResponse(
            status_code=app_exc.status_code,
            content=app_exc.to_dict(),
            headers=headers,
        )
