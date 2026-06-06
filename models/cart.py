"""Cart model.

Each session or logged-in user gets exactly one active cart.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.cart_item import CartItem
    from models.user import User


class Cart(ModelBase, table=True):
    """A shopping cart (one per session or user)."""

    __tablename__ = "carts"

    session_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), unique=True, nullable=True, index=True),
    )
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
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
    user: Optional["User"] = Relationship(back_populates="carts")
    cart_items: List["CartItem"] = Relationship(
        back_populates="cart",
        cascade_delete=True,
    )
