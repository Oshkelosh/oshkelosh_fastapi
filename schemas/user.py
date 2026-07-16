"""User schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from schemas.address import Address
from schemas.base import PaginatedResponse


def _validate_password_strength(value: str) -> str:
    if not any(c.isupper() for c in value):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in value):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit")
    return value


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _coerce_address(value: Any) -> Optional[Address]:
    if value is None:
        return None
    if isinstance(value, Address):
        return value
    if isinstance(value, dict):
        return Address.model_validate(value)
    raise ValueError("Invalid address")


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Dict[str, Any]] = None
    default_billing_address: Optional[Dict[str, Any]] = None
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
        return _validate_password_strength(v)


class InitialAdminCreate(_PasswordMixin):
    """First-admin bootstrap payload — identity only, no customer addresses."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _normalize_email(v)
        return v


class UserRegister(_PasswordMixin):
    """Public registration payload — identity plus shipping/billing addresses."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Address
    default_billing_address: Optional[Address] = None
    billing_same_as_shipping: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _normalize_email(v)
        return v

    @field_validator("default_shipping_address", "default_billing_address", mode="before")
    @classmethod
    def _parse_addresses(cls, v: Any) -> Any:
        return _coerce_address(v) if v is not None else None

    @model_validator(mode="after")
    def resolve_billing(self) -> "UserRegister":
        if self.billing_same_as_shipping or self.default_billing_address is None:
            self.default_billing_address = self.default_shipping_address.model_copy()
        return self


# ── Create (admin) ──────────────────────────────────────────────────


class UserCreate(UserBase, _PasswordMixin):
    """Admin-only user creation with full profile fields."""

    default_shipping_address: Optional[Address] = None  # type: ignore[assignment]
    default_billing_address: Optional[Address] = None  # type: ignore[assignment]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _normalize_email(v)
        return v

    @field_validator("default_shipping_address", "default_billing_address", mode="before")
    @classmethod
    def _parse_addresses(cls, v: Any) -> Any:
        return _coerce_address(v) if v is not None else None


# ── Update ──────────────────────────────────────────────────────────


class UserProfileUpdate(BaseModel):
    """Self-service profile update (no privilege or ban fields)."""

    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Address] = None
    default_billing_address: Optional[Address] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    push_token: Optional[str] = Field(default=None, max_length=512)
    push_provider: Optional[str] = Field(default=None, max_length=32)

    @field_validator("default_shipping_address", "default_billing_address", mode="before")
    @classmethod
    def _parse_addresses(cls, v: Any) -> Any:
        return _coerce_address(v) if v is not None else None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_password_strength(v)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    default_shipping_address: Optional[Address] = None
    default_billing_address: Optional[Address] = None
    banned: Optional[bool] = None
    verified: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("default_shipping_address", "default_billing_address", mode="before")
    @classmethod
    def _parse_addresses(cls, v: Any) -> Any:
        return _coerce_address(v) if v is not None else None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_password_strength(v)


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

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _normalize_email(v)
        return v


class ResetPasswordRequest(_PasswordMixin):
    token: str = Field(min_length=16, max_length=128)


class UserList(PaginatedResponse["UserRead"]):
    """Paginated list of users."""


# ── Login ───────────────────────────────────────────────────────────


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _normalize_email(v)
        return v


# ── Token ───────────────────────────────────────────────────────────


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterResponse(Token):
    """Registration result: profile plus JWT session."""

    user: UserRead


class TokenPayload(BaseModel):
    sub: int  # user id
    exp: datetime
