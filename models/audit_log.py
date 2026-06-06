"""Audit trail for admin and API mutations."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlmodel import Field

from app.db.base import ModelBase, utc_now


class AuditLog(ModelBase, table=True):
    """Who changed what and when."""

    __tablename__ = "audit_logs"

    actor_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    action: str = Field(sa_column=Column(String(50), nullable=False))
    resource_type: str = Field(sa_column=Column(String(50), nullable=False))
    resource_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    changes: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    ip_address: Optional[str] = Field(
        default=None,
        sa_column=Column(String(45), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    detail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
