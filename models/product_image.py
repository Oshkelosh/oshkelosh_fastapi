"""ProductImage model.

Separate table so images can be sorted and have alt-text independently of
the JSON ``images`` field on ``Product``.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.product import Product


class ProductImage(ModelBase, table=True):
    """An image belonging to a product."""

    __tablename__ = "product_images"

    product_id: int = Field(
        sa_column=Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    )
    url: str = Field(sa_column=Column(String(2000), nullable=False))
    alt_text: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )

    # ── Relationships ──────────────────────────────────────────────
    product: "Product" = Relationship(back_populates="images_rel")
