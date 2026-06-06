"""Webhook model.

Webhooks are delivered by the addon system when configured events fire.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Text
from sqlmodel import Field

from app.db.base import ModelBase, utc_now


class Webhook(ModelBase, table=True):
    """An outbound webhook subscription."""

    __tablename__ = "webhooks"

    addon_id: str = Field(
        sa_column=Column(String(100), nullable=False),
    )
    url: str = Field(
        sa_column=Column(String(2000), nullable=False),
    )
    events: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
    secret: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    last_response: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
