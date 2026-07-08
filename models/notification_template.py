"""Merchant-editable notification message templates."""

from sqlalchemy import Boolean, Column, String, Text, UniqueConstraint
from sqlmodel import Field

from app.db.base import ModelBase


class NotificationTemplate(ModelBase, table=True):
    """Override default copy for a notification event and channel."""

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("event_key", "channel", name="uq_notification_templates_event_channel"),
    )

    event_key: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    channel: str = Field(sa_column=Column(String(16), nullable=False, index=True))
    subject: str = Field(sa_column=Column(String(512), nullable=False))
    body: str = Field(sa_column=Column(Text, nullable=False))
    is_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
