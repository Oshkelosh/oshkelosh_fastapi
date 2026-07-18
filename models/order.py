"""Order model."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.order_item import OrderItem
    from models.user import User


class Order(ModelBase, table=True):
    """A customer purchase order."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_user_id", "user_id"),
        Index("idx_orders_status_created_at", "status", "created_at"),
    )

    session_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    # Valid statuses: pending / paid / shipped / delivered / cancelled
    status: str = Field(
        default="pending",
        sa_column=Column(String(20), nullable=False, server_default="pending"),
    )
    total_cents: int = Field(
        ge=0,
        description="Grand total in cents (merchandise + tax + shipping).",
        sa_column=Column(Integer, nullable=False),
    )
    tax_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    shipping_cents: int = Field(
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    currency: str = Field(
        default="usd",
        sa_column=Column(String(10), nullable=False, server_default="usd"),
    )

    payment_processor_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(50), nullable=True),
    )
    payment_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    payment_charge_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )

    shipping_address: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    billing_address: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    shipping_selections: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    supplier_orders: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-supplier fulfillment results keyed by shipping group, for idempotent retry.",
        sa_column=Column(JSON, nullable=True),
    )
    notes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    tracking_number: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    tracking_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(2048), nullable=True),
    )
    carrier: Optional[str] = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
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
    user: Optional["User"] = Relationship(back_populates="orders")
    order_items: List["OrderItem"] = Relationship(
        back_populates="order",
        cascade_delete=True,
    )
