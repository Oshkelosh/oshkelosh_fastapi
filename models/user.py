"""Shop accounts for storefront customers and administrators."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.cart import Cart
    from models.order import Order
    from models.product import Product


class User(ModelBase, table=True):
    """Shop user account."""

    __tablename__ = "users"

    email: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False, index=True),
    )
    password_hash: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    banned: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    verified: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    verified_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    is_admin: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    full_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    phone: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    push_provider: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    push_token: Optional[str] = Field(
        default=None,
        sa_column=Column(String(512), nullable=True),
    )
    default_shipping_address: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    payment_customer_ids: Optional[Dict[str, str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    oauth_identities: Optional[Dict[str, str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    email_verification_token: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    email_verification_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    password_reset_token: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    password_reset_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )

    # ── Relationships ──────────────────────────────────────────────
    products: List["Product"] = Relationship(
        back_populates="created_by_user",
        sa_relationship_kwargs={"foreign_keys": "Product.created_by"},
    )
    carts: List["Cart"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    orders: List["Order"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )

    @property
    def auth_methods(self) -> List[str]:
        """Login methods available for this account (no OAuth subject ids)."""
        methods: List[str] = []
        if self.password_hash:
            methods.append("password")
        if self.oauth_identities:
            methods.extend(sorted(self.oauth_identities.keys()))
        return methods
