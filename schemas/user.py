"""User schemas.

Prices are stored as cents (int) in the DB and exposed as ``Decimal`` in
API responses via ``Field(serialization_alias=..., json_schema_extra=...)``
or manual validators.  See the ``price_cents`` → ``price`` pattern in
product schemas for the full technique.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from schemas.base import PaginatedResponse


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = True
    is_admin: bool = False


# ── Register (public) ───────────────────────────────────────────────


class _PasswordMixin(BaseModel):
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password – it will be hashed server-side.",
    )

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserRegister(_PasswordMixin):
    """Public registration payload — no privilege fields."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)


# ── Create (admin) ──────────────────────────────────────────────────


class UserCreate(UserBase, _PasswordMixin):
    """Admin-only user creation with full profile fields."""


# ── Update ──────────────────────────────────────────────────────────


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


# ── Read ────────────────────────────────────────────────────────────


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserList(PaginatedResponse["UserRead"]):
    """Paginated list of users."""


# ── Login ───────────────────────────────────────────────────────────


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ── Token ───────────────────────────────────────────────────────────


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: int  # user id
    exp: datetime
