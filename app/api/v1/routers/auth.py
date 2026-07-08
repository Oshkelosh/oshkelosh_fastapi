"""Authentication endpoints.

Provides user registration, login, logout, profile retrieval, and token
refresh via JWT Bearer tokens.
"""

from fastapi import APIRouter, Depends, Query, Request, status
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
from app.db.connection import get_session, mark_instance_dirty
from models.user import User
from schemas.base import MessageResponse
from schemas.user import (
    EmailVerifyRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserLogin,
    UserProfileUpdate,
    UserRead,
    UserRegister,
)
from app.services.user_accounts import (
    mark_user_verified,
    reset_password_with_token,
    send_password_reset_email,
    send_verification_email,
    verify_email_with_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_ALLOWED_PUSH_PROVIDERS = frozenset({"fcm", "onesignal", "pusher_beams"})


def _as_user_read(user: User) -> UserRead:
    return UserRead.from_user(user)


def _apply_push_subscription(user: User, body: UserProfileUpdate) -> None:
    from app.services.addons import get_notification_addon_for_channel

    fields_set = body.model_fields_set
    if "push_token" not in fields_set and "push_provider" not in fields_set:
        return

    token = (body.push_token or "").strip() or None
    provider = (body.push_provider or "").strip() or None

    if not token and not provider:
        user.push_token = None
        user.push_provider = None
        return

    if not token or not provider:
        raise ValidationError(
            message="push_token and push_provider must both be set or cleared together"
        )
    if provider not in _ALLOWED_PUSH_PROVIDERS:
        raise ValidationError(message=f"Unsupported push provider: {provider}")

    addon = get_notification_addon_for_channel("push")
    if addon is None or addon.addon_id != provider:
        raise ValidationError(message="That push provider is not currently enabled")

    user.push_token = token
    user.push_provider = provider


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

from app.core.user_access import ensure_user_can_access


def _build_token_response(user: User) -> dict:
    """Create a JWT token pair and return it as a plain dict."""
    from app.services.auth_tokens import build_token_response

    return build_token_response(user)


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
) -> UserRead:
    """Register a new user account."""
    existing = await session.execute(
        select(User).where(col(User.email) == body.email)
    )
    if existing.first() is not None:
        raise ValidationError(message="A user with this email already exists")

    auto_verify = not settings.require_email_verification
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        phone=body.phone,
        banned=False,
        verified=auto_verify,
        is_admin=False,
    )
    if auto_verify:
        mark_user_verified(user)

    session.add(user)
    await session.flush()
    await session.refresh(user)

    if not auto_verify:
        await send_verification_email(session, user)
        mark_instance_dirty(session, user)
        await session.flush()
        await session.refresh(user)

    from app.services.lifecycle_events import (
        EVENT_USER_REGISTERED,
        build_user_registered_payload,
        dispatch_lifecycle_event,
    )

    await dispatch_lifecycle_event(
        session,
        EVENT_USER_REGISTERED,
        build_user_registered_payload(user),
    )

    return _as_user_read(user)


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

    if user is None:
        raise AuthenticationError(message="Invalid email or password")
    if user.password_hash is None:
        raise AuthenticationError(message="This account uses social sign-in")
    if not verify_password(body.password, user.password_hash):
        raise AuthenticationError(message="Invalid email or password")

    ensure_user_can_access(user)
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
) -> UserRead:
    """Return the authenticated user's profile."""
    user = await session.get(User, current_user.id)
    if user is None:
        raise NotFound(resource_name="User", resource_id=str(current_user.id))
    return _as_user_read(user)


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Update current user profile",
    description="Update profile fields for the authenticated user.",
)
async def update_me(
    body: UserProfileUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    session=Depends(get_session),
) -> UserRead:
    """Update the authenticated user's profile."""
    user = await session.get(User, current_user.id)
    if user is None:
        raise NotFound(resource_name="User", resource_id=str(current_user.id))

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.phone is not None:
        user.phone = body.phone
    if body.default_shipping_address is not None:
        user.default_shipping_address = body.default_shipping_address
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    _apply_push_subscription(user, body)

    mark_instance_dirty(session, user)
    await session.flush()
    await session.refresh(user)
    return _as_user_read(user)


@router.get(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email (link)",
    description="Confirm email ownership using the token from the verification email.",
)
async def verify_email_link(
    token: str = Query(..., min_length=16, max_length=128),
    session=Depends(get_session),
) -> MessageResponse:
    user = await verify_email_with_token(session, token)
    mark_instance_dirty(session, user)
    await session.flush()
    return MessageResponse(message="Email verified successfully")


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email",
    description="Confirm email ownership using the token from the verification email.",
)
async def verify_email(
    body: EmailVerifyRequest,
    session=Depends(get_session),
) -> MessageResponse:
    user = await verify_email_with_token(session, body.token)
    mark_instance_dirty(session, user)
    await session.flush()
    return MessageResponse(message="Email verified successfully")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    description="Send a password reset link if the account exists.",
)
@limiter.limit(settings.rate_limit_register)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session=Depends(get_session),
) -> MessageResponse:
    result = await session.execute(
        select(User).where(col(User.email) == body.email)
    )
    user = result.scalar_one_or_none()
    if user is not None and not user.banned:
        await send_password_reset_email(session, user)
        mark_instance_dirty(session, user)
        await session.flush()
    return MessageResponse(
        message="If that email exists, a password reset link has been sent."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password",
    description="Set a new password using a valid reset token.",
)
@limiter.limit(settings.rate_limit_register)
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    session=Depends(get_session),
) -> MessageResponse:
    user = await reset_password_with_token(session, body.token, body.password)
    mark_instance_dirty(session, user)
    await session.flush()
    return MessageResponse(message="Password reset successfully")


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
    if result is None:
        raise AuthenticationError("User not found")

    ensure_user_can_access(result)
    return _build_token_response(result)
