"""Idempotency records for POST /orders."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.order import Order
    from models.user import User


class OrderIdempotencyKey(ModelBase, table=True):
    """Maps a user + idempotency key hash to a created order."""

    __tablename__ = "order_idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key_hash", name="uq_order_idem_user_key"),)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    key_hash: str = Field(
        sa_column=Column(String(64), nullable=False),
    )
    order_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: Optional["User"] = Relationship()
    order: Optional["Order"] = Relationship()
