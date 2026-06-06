"""User model.

Each row represents a shop administrator / staff user.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
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
    password_hash: str = Field(sa_column=Column(Text, nullable=False))
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    is_admin: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    full_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
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
