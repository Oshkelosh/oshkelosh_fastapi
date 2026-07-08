"""User account helpers: verification, password reset, shipping address."""

from __future__ import annotations

import logging
import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlmodel import col, select

from app.config import settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.security import hash_password
from models.user import User

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_expired(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    return _as_utc(expires_at) < _utc_now()


def _public_app_url() -> str:
    if settings.public_app_url:
        return settings.public_app_url.rstrip("/")
    if settings.cors_origins:
        return settings.cors_origins[0].rstrip("/")
    return "http://localhost:8000"


def generate_account_token() -> str:
    return secrets.token_urlsafe(32)


def issue_email_verification(user: User) -> str:
    token = generate_account_token()
    user.email_verification_token = token
    user.email_verification_expires_at = _utc_now() + timedelta(
        hours=settings.email_verification_expire_hours
    )
    return token


def issue_password_reset(user: User) -> str:
    token = generate_account_token()
    user.password_reset_token = token
    user.password_reset_expires_at = _utc_now() + timedelta(
        hours=settings.password_reset_expire_hours
    )
    return token


def clear_email_verification(user: User) -> None:
    user.email_verification_token = None
    user.email_verification_expires_at = None


def clear_password_reset(user: User) -> None:
    user.password_reset_token = None
    user.password_reset_expires_at = None


def mark_user_verified(user: User) -> None:
    user.verified = True
    user.verified_at = _utc_now()
    clear_email_verification(user)


async def send_verification_email(session: Any, user: User) -> None:
    from app.services.notification_dispatch import dispatch_notification

    token = issue_email_verification(user)
    verify_url = f"{_public_app_url()}/verify-email?token={token}"
    try:
        await dispatch_notification(
            session,
            "email_verification",
            email=user.email,
            context={
                "verify_url": verify_url,
                "expire_hours": settings.email_verification_expire_hours,
            },
        )
    except Exception:
        logger.exception("Failed to send verification email to user %s", user.id)


async def send_password_reset_email(session: Any, user: User) -> None:
    from app.services.notification_dispatch import dispatch_notification

    token = issue_password_reset(user)
    reset_url = f"{_public_app_url()}/reset-password?token={token}"
    try:
        await dispatch_notification(
            session,
            "password_reset",
            email=user.email,
            context={
                "reset_url": reset_url,
                "expire_hours": settings.password_reset_expire_hours,
            },
        )
    except Exception:
        logger.exception("Failed to send password reset email to user %s", user.id)


async def verify_email_with_token(session: Any, token: str) -> User:
    result = await session.execute(
        select(User).where(col(User.email_verification_token) == token)
    )
    user = result.scalar_one_or_none()
    if user is None or _is_expired(user.email_verification_expires_at):
        raise ValidationError(message="Invalid or expired verification token")
    mark_user_verified(user)
    return user


async def reset_password_with_token(session: Any, token: str, new_password: str) -> User:
    result = await session.execute(
        select(User).where(col(User.password_reset_token) == token)
    )
    user = result.scalar_one_or_none()
    if user is None or _is_expired(user.password_reset_expires_at):
        raise AuthenticationError(message="Invalid or expired reset token")
    user.password_hash = hash_password(new_password)
    clear_password_reset(user)
    return user


def resolve_order_shipping_address(
    user: User,
    shipping_address: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Use explicit address or fall back to the user's saved default."""
    address = deepcopy(shipping_address) if shipping_address else None
    if address is None and user.default_shipping_address:
        address = deepcopy(user.default_shipping_address)
    if address is None:
        return None

    if user.email and not address.get("email"):
        address["email"] = user.email
    if user.phone and not address.get("phone"):
        address["phone"] = user.phone
    return address


async def link_payment_customer(
    session: Any,
    user_id: int,
    processor_id: str,
    customer_id: str,
) -> None:
    if not processor_id or not customer_id:
        return
    user = await session.get(User, user_id)
    if user is None:
        return
    ids = dict(user.payment_customer_ids or {})
    ids[processor_id] = customer_id
    user.payment_customer_ids = ids
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(user)
    await session.flush()
