"""First-admin bootstrap helpers."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlmodel import col

from app.core.exceptions import ValidationError
from app.core.security import hash_password
from models.user import User
from schemas.user import UserRegister
from app.services.user_accounts import mark_user_verified


async def has_admin_user(session: Any) -> bool:
    """Return True if at least one active admin user exists."""
    result = await session.execute(
        select(User.id)
        .where(col(User.is_admin).is_(True))
        .where(col(User.banned).is_(False))
        .limit(1)
    )
    return result.first() is not None


async def create_initial_admin(
    session: Any,
    *,
    email: str,
    password: str,
    full_name: Optional[str] = None,
) -> User:
    """Create the first admin user. Raises if an admin already exists."""
    if await has_admin_user(session):
        raise ValidationError(message="An admin user already exists")

    validated = UserRegister(email=email, password=password, full_name=full_name)

    user = User(
        email=validated.email,
        password_hash=hash_password(validated.password),
        full_name=validated.full_name,
        phone=validated.phone,
        banned=False,
        verified=True,
        is_admin=True,
    )
    mark_user_verified(user)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
