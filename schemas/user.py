"""User schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from schemas.base import PaginatedResponse


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Dict[str, Any]] = None
    banned: bool = False
    verified: bool = True
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
    phone: Optional[str] = Field(default=None, max_length=32)


# ── Create (admin) ──────────────────────────────────────────────────


class UserCreate(UserBase, _PasswordMixin):
    """Admin-only user creation with full profile fields."""


# ── Update ──────────────────────────────────────────────────────────


class UserProfileUpdate(BaseModel):
    """Self-service profile update (no privilege or ban fields)."""

    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Dict[str, Any]] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    push_token: Optional[str] = Field(default=None, max_length=512)
    push_provider: Optional[str] = Field(default=None, max_length=32)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Dict[str, Any]] = None
    banned: Optional[bool] = None
    verified: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


# ── Read ────────────────────────────────────────────────────────────


class UserRead(UserBase):
    id: int
    verified_at: Optional[datetime] = None
    auth_methods: List[str] = Field(default_factory=list)
    push_enabled: bool = Field(
        default=False,
        description="Whether the user has an active push subscription token saved.",
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_user(cls, user: Any) -> "UserRead":
        data = cls.model_validate(user)
        return data.model_copy(update={"push_enabled": bool(getattr(user, "push_token", None))})


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(_PasswordMixin):
    token: str = Field(min_length=16, max_length=128)


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
