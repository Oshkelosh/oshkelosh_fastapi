"""Category model.

Categories form a tree (via ``parent_id`` self-referential FK).
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlmodel import Field, Relationship

from app.db.base import ModelBase, utc_now

if TYPE_CHECKING:
    from models.product import Product


class Category(ModelBase, table=True):
    """Product category (hierarchical)."""

    __tablename__ = "categories"

    name: str = Field(sa_column=Column(String(200), nullable=False))
    slug: str = Field(
        sa_column=Column(String(200), unique=True, nullable=False, index=True),
    )
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    meta_title: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    meta_description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    parent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
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
    parent: Optional["Category"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "Category.id"},
    )
    children: List["Category"] = Relationship(back_populates="parent")
    products: List["Product"] = Relationship(back_populates="category_rel")
