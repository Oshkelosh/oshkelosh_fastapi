"""Singleton outbound webhook receiver (HMAC-signed deliveries)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlmodel import Field

from app.db.base import ModelBase, utc_now


class OutboundWebhookEndpoint(ModelBase, table=True):
    """Merchant-configured HTTPS receiver for signed commerce events."""

    __tablename__ = "outbound_webhook_endpoints"

    enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    url: str | None = Field(default=None, sa_column=Column(String(2048), nullable=True))
    secret: str | None = Field(default=None, sa_column=Column(String(128), nullable=True))
    events: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    last_status: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    last_sent_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
