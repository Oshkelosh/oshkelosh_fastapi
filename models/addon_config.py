"""AddonConfig model.

Stores configuration for pluggable addons / extensions.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import Boolean, Column, DateTime, JSON, String
from sqlmodel import Field

from app.db.base import ModelBase, utc_now


class AddonConfig(ModelBase, table=True):
    """Addon configuration row."""

    __tablename__ = "addon_configs"

    addon_id: str = Field(
        sa_column=Column(String(100), nullable=False),
    )
    addon_type: str = Field(
        sa_column=Column(String(100), nullable=False),
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    is_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )

    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
