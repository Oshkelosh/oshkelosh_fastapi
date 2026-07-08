"""Shared admin session cookie helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, unquote

from fastapi.responses import RedirectResponse, Response
from jose import JWTError, jwt

from app.config import settings

SESSION_COOKIE_NAME = "oshkelosh_admin"
SESSION_ALGORITHM = "HS256"


def encode_session(user_id: int, expires_delta: timedelta = timedelta(hours=24)) -> str:
    """Create a signed session token."""
    expire = datetime.now(tz=timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "admin_session",
        "csrf": secrets.token_urlsafe(32),
    }
    return jwt.encode(payload, settings.session_secret, algorithm=SESSION_ALGORITHM)


def decode_session(token: str) -> dict[str, Any]:
    """Decode and verify the session cookie."""
    try:
        return jwt.decode(token, settings.session_secret, algorithms=[SESSION_ALGORITHM])
    except JWTError:
        return {}


def cookie_secure() -> bool:
    return settings.app_env == "production"


def set_session_cookie(response: RedirectResponse, user_id: int) -> RedirectResponse:
    """Set the session cookie on a redirect response."""
    token = encode_session(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite=settings.admin_cookie_samesite,
        secure=cookie_secure(),
        max_age=86400,
        path="/",
    )
    return response


def clear_session_cookie(response: RedirectResponse) -> RedirectResponse:
    """Clear the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response


FLASH_COOKIE_NAME = "_oshkelosh_flash"


def set_flash_cookie(response: Response, message: str) -> Response:
    """Set a short-lived flash message cookie for admin redirects."""
    response.set_cookie(
        key=FLASH_COOKIE_NAME,
        value=quote(message, safe=""),
        httponly=True,
        max_age=settings.flash_cookie_max_age,
        path="/",
    )
    return response


def read_flash_cookie(raw_value: str) -> str:
    """Decode a flash cookie value (supports legacy unencoded ASCII messages)."""
    if not raw_value:
        return ""
    try:
        return unquote(raw_value)
    except ValueError:
        return raw_value
