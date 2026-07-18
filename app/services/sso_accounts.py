"""SSO account lookup, linking, and creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import col, select

from app.core.exceptions import AuthenticationError
from app.services.user_accounts import mark_user_verified
from models.user import User


@dataclass
class SsoProfile:
    """Normalized identity from an OAuth/OIDC provider."""

    provider: str
    subject: str
    email: str
    email_verified: bool
    full_name: Optional[str] = None


async def find_user_by_oauth_identity(
    session: Any,
    provider: str,
    subject: str,
) -> Optional[User]:
    result = await session.execute(
        select(User).where(col(User.oauth_identities).isnot(None))
    )
    for user in result.scalars().all():
        identities = user.oauth_identities or {}
        if identities.get(provider) == subject:
            return user
    return None


async def find_or_create_sso_user(session: Any, profile: SsoProfile) -> User:
    """Find, link, or create a user from an SSO profile."""
    email = profile.email.strip().lower()
    if not email:
        raise AuthenticationError(message="SSO provider did not return an email address")

    user = await find_user_by_oauth_identity(session, profile.provider, profile.subject)
    if user is None:
        result = await session.execute(select(User).where(col(User.email) == email))
        user = result.scalar_one_or_none()
        if user is not None and not profile.email_verified:
            # Linking by email requires the provider to have verified it,
            # otherwise anyone who registers the victim's address at the IdP
            # takes over the existing account.
            raise AuthenticationError(
                message=(
                    "This email is already registered. Verify the email with your "
                    "SSO provider or sign in with your password first."
                )
            )

    if user is not None:
        if user.banned:
            raise AuthenticationError(message="User account is banned")
        identities = dict(user.oauth_identities or {})
        identities[profile.provider] = profile.subject
        user.oauth_identities = identities
        if profile.full_name and not user.full_name:
            user.full_name = profile.full_name
        if profile.email_verified:
            mark_user_verified(user)
        return user

    user = User(
        email=email,
        password_hash=None,
        full_name=profile.full_name,
        banned=False,
        verified=profile.email_verified,
        is_admin=False,
        oauth_identities={profile.provider: profile.subject},
    )
    if profile.email_verified:
        mark_user_verified(user)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
