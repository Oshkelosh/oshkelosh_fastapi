"""First-admin bootstrap helpers."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlmodel import col

from app.core.exceptions import ValidationError
from app.core.security import hash_password
from models.user import User
from schemas.user import UserRegister


async def has_admin_user(session: Any) -> bool:
    """Return True if at least one active admin user exists."""
    result = await session.execute(
        select(User.id)
        .where(col(User.is_admin).is_(True))
        .where(col(User.is_active).is_(True))
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
        is_active=True,
        is_admin=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
