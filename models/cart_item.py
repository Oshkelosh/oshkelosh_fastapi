"""CartItem model."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.cart import Cart
    from models.product import Product


class CartItem(ModelBase, table=True):
    """An item inside a cart."""

    __tablename__ = "cart_items"

    cart_id: int = Field(
        sa_column=Column(Integer, ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
    )
    product_id: int = Field(
        sa_column=Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    )
    quantity: int = Field(
        default=1,
        ge=1,
        sa_column=Column(Integer, nullable=False),
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
    cart: "Cart" = Relationship(back_populates="cart_items")
    product: "Product" = Relationship(back_populates="cart_items")
