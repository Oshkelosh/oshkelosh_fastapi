"""Shared user access checks for API auth."""

from __future__ import annotations

from app.core.exceptions import AuthenticationError
from models.user import User


def ensure_user_can_access(user: User) -> None:
    """Raise if the user may not authenticate or use protected APIs."""
    if user.banned:
        raise AuthenticationError("User account is banned")
    if not user.verified:
        raise AuthenticationError("Email address is not verified")
