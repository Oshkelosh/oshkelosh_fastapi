"""Storefront handlers for auth email deep-links (verify / reset password)."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from app.core.exceptions import AuthenticationError, ValidationError
from app.db.connection import get_session, mark_instance_dirty
from app.services.user_accounts import (
    validate_password_reset_token,
    verify_email_with_token,
)
from app.storefront.seo_routes import serve_spa_html

router = APIRouter(tags=["auth-links"], include_in_schema=False)

_TOKEN_MIN = 16
_TOKEN_MAX = 128


def _login_redirect(auth: str, *, reason: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {"auth": auth}
    if reason:
        params["reason"] = reason
    return RedirectResponse(url=f"/login?{urlencode(params)}", status_code=302)


def _forgot_password_redirect(*, reason: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {"auth": "reset_failed"}
    if reason:
        params["reason"] = reason
    return RedirectResponse(url=f"/forgot-password?{urlencode(params)}", status_code=302)


def _token_reason(token: str | None) -> str | None:
    if token is None or not token.strip():
        return "missing"
    if len(token) < _TOKEN_MIN or len(token) > _TOKEN_MAX:
        return "invalid"
    return None


@router.get("/verify-email")
async def verify_email_link(
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Consume the email verification token and redirect into the SPA login page."""
    token = request.query_params.get("token")
    reason = _token_reason(token)
    if reason is not None:
        return _login_redirect("verify_failed", reason=reason)

    assert token is not None  # narrowed by _token_reason
    try:
        user = await verify_email_with_token(session, token)
    except ValidationError:
        return _login_redirect("verify_failed", reason="invalid")

    mark_instance_dirty(session, user)
    await session.flush()
    return _login_redirect("verified")


@router.get("/reset-password")
async def reset_password_link(
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Validate a reset token without consuming it; serve SPA or redirect on failure."""
    token = request.query_params.get("token")
    reason = _token_reason(token)
    if reason is not None:
        return _forgot_password_redirect(reason=reason)

    assert token is not None  # narrowed by _token_reason
    try:
        await validate_password_reset_token(session, token)
    except AuthenticationError:
        return _forgot_password_redirect(reason="invalid")

    return await serve_spa_html(request, session)


def register_auth_link_routes(app) -> None:
    """Register auth deep-link routes before the static storefront mount."""
    app.include_router(router)
