"""OrderItem model.

Denormalised copies of product name / SKU at the time of purchase so that
historical orders remain accurate even if the product catalogue changes.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
)
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.order import Order
    from models.product import Product
    from models.product_variant import ProductVariant


class OrderItem(ModelBase, table=True):
    """A single line item within an order."""

    __tablename__ = "order_items"

    order_id: int = Field(
        sa_column=Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    )
    product_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
    )
    variant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True),
    )
    variant_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    product_name: str = Field(
        sa_column=Column(String(255), nullable=False),
    )
    product_sku: str = Field(
        sa_column=Column(String(100), nullable=False),
    )
    quantity: int = Field(
        ge=1,
        sa_column=Column(Integer, nullable=False),
    )
    unit_price_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False),
    )
    total_price_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )

    # ── Relationships ──────────────────────────────────────────────
    order: "Order" = Relationship(back_populates="order_items")
    product: Optional["Product"] = Relationship(back_populates="order_items")
    variant: Optional["ProductVariant"] = Relationship(back_populates="order_items")
