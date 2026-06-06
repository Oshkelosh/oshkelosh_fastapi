"""
Security utilities: JWT handling and password hashing.

Uses python-jose for JWT operations and bcrypt for password hashing.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=settings.bcrypt_rounds),
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


# ------------------------------------------------------------------
# JWT helpers
# ------------------------------------------------------------------

def _get_refresh_secret() -> str:
    """Return the secret used for refresh tokens."""
    return settings.refresh_secret


def create_access_token(
    subject: str | int,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token."""
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    subject: str | int,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT refresh token."""
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta
        or timedelta(days=settings.jwt_refresh_token_expire_days)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "refresh",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _get_refresh_secret(), algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and verify a JWT."""
    payload = jwt.decode(
        token,
        _get_refresh_secret() if expected_type == "refresh" else settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != expected_type:
        raise JWTError(f"Expected token type '{expected_type}', got '{payload.get('type')}'")
    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode an access token."""
    return decode_token(token, expected_type="access")


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode a refresh token."""
    return decode_token(token, expected_type="refresh")
