"""Idempotency records for external webhook deliveries."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field

from app.db.base import ModelBase, utc_now


class ProcessedWebhookEvent(ModelBase, table=True):
    """Payment-provider webhook events already handled (dedupe/replay guard)."""

    __tablename__ = "processed_webhook_events"

    event_id: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False, index=True),
    )
    provider: str = Field(
        sa_column=Column(String(50), nullable=False),
    )
    event_type: str = Field(
        sa_column=Column(String(100), nullable=False, server_default=""),
    )
    processed_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
