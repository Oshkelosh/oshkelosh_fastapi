"""
FastAPI dependency functions for authentication and authorization.

These are used with ``Depends()`` in route handlers to enforce
auth requirements declaratively.
"""

from typing import Optional

from fastapi import Depends, Request
from jose import JWTError
from pydantic import BaseModel

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token
from app.db.connection import get_session
from app.storage import StorageBackend, get_storage
from models.user import User


class CurrentUser(BaseModel):
    """Authenticated user loaded from the database."""

    id: int
    email: Optional[str] = None
    role: str = "user"
    is_active: bool = True
    is_admin: bool = False


async def get_current_user(
    request: Request,
    session=Depends(get_session),
) -> CurrentUser:
    """Validate JWT and load the current user from the database.

    Expects: ``Authorization: Bearer <access_token>``

    Raises:
        AuthenticationError: If the header is missing, token invalid, or user inactive.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise AuthenticationError("Authorization header is required")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Invalid authorization scheme")

    try:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if not sub:
            raise AuthenticationError("Token has no subject")
        user_id = int(sub)
    except (JWTError, ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    user = await session.get(User, user_id)
    if user is None:
        raise AuthenticationError("User not found")
    if not user.is_active:
        raise AuthenticationError("User account is deactivated")

    return CurrentUser(
        id=user.id,
        email=user.email,
        role="admin" if user.is_admin else "user",
        is_active=user.is_active,
        is_admin=user.is_admin,
    )


def get_admin_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require that the authenticated user has admin privileges.

    Raises:
        AuthorizationError: If the user is not an admin.
    """
    if not current_user.is_admin:
        raise AuthorizationError("Admin privileges required")
    return current_user


def require_active_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Require that the authenticated user is active.

    Raises:
        AuthenticationError: If the user account is deactivated.
    """
    if not current_user.is_active:
        raise AuthenticationError("User account is deactivated")
    return current_user
