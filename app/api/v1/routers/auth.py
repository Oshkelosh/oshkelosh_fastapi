"""Authentication endpoints.

Provides user registration, login, logout, profile retrieval, and token
refresh via JWT Bearer tokens.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import EmailStr
from sqlmodel import col, select

from app.config import settings
from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import AuthenticationError, NotFound, ValidationError
from app.core.rate_limit import limiter
from app.core.security import (
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.db.connection import get_session
from models.user import User
from schemas.user import Token, UserLogin, UserRead, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_token_response(user: User) -> dict:
    """Create a JWT token pair and return it as a plain dict."""
    from app.core.security import create_access_token, create_refresh_token

    extra = {"email": user.email, "role": "admin" if user.is_admin else "user"}
    return {
        "access_token": create_access_token(user.id, extra_claims=extra),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with the provided credentials.",
)
@limiter.limit(settings.rate_limit_register)
async def register(
    request: Request,
    body: UserRegister,
    session=Depends(get_session),
) -> User:
    """Register a new user account."""
    # Check for duplicate email
    existing = await session.execute(
        select(User).where(col(User.email) == body.email)
    )
    if existing.first() is not None:
        raise ValidationError(message="A user with this email already exists")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        is_active=True,
        is_admin=False,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


@router.post(
    "/login",
    response_model=Token,
    summary="Login",
    description="Authenticate with email and password. Returns a JWT access token and refresh token.",
)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request,
    body: UserLogin,
    session=Depends(get_session),
) -> dict:
    """Authenticate a user and return JWT tokens."""
    result = await session.execute(
        select(User).where(col(User.email) == body.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise AuthenticationError(message="Invalid email or password")

    if not user.is_active:
        raise AuthenticationError(message="User account is deactivated")

    return _build_token_response(user)


@router.post(
    "/logout",
    response_model=dict,
    summary="Logout",
    description="Invalidate the current access token. The client should discard stored tokens.",
)
async def logout(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Logout – the client should discard its stored JWT tokens."""
    # Note: JWTs are stateless, so true server-side invalidation requires
    # a token blocklist. For now we just confirm the logout.
    return {"message": "Successfully logged out"}


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user profile",
    description="Return the profile of the currently authenticated user.",
)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> User:
    """Return the authenticated user's profile."""
    user = await session.get(User, current_user.id)
    if user is None:
        raise NotFound(resource_name="User", resource_id=str(current_user.id))
    return user


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token pair.",
)
@limiter.limit(settings.rate_limit_refresh)
async def refresh(
    request: Request,
    session=Depends(get_session),
) -> dict:
    """Refresh an access token using a refresh token from the Authorization header."""
    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise AuthenticationError("Authorization header is required")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Invalid authorization scheme")

    try:
        payload = decode_refresh_token(token)
        user_id = int(payload["sub"])
    except Exception as exc:
        raise AuthenticationError("Invalid or expired refresh token") from exc

    result = await session.get(User, user_id)
    if result is None or not result.is_active:
        raise AuthenticationError("User not found or deactivated")

    return _build_token_response(result)
