"""Manual supplier definitions for non-API fulfillment."""

from typing import Optional

from sqlalchemy import Boolean, Column, String, Text
from sqlmodel import Field

from app.db.base import ModelBase


class ManualSupplier(ModelBase, table=True):
    """A merchant-defined supplier fulfilled outside automated APIs."""

    __tablename__ = "manual_suppliers"

    slug: str = Field(
        sa_column=Column(String(100), nullable=False, unique=True),
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    contact_email: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    contact_phone: Optional[str] = Field(
        default=None,
        sa_column=Column(String(50), nullable=True),
    )
    notes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
