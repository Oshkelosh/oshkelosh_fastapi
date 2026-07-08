"""Background job records for long-running admin operations."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, JSON, String, Text
from sqlmodel import Field, SQLModel

from app.db.base import utc_now


class BackgroundJob(SQLModel, table=True):
    """Persisted admin background job with incremental progress."""

    __tablename__ = "background_jobs"

    id: str = Field(sa_column=Column(String(36), primary_key=True, nullable=False))
    job_type: str = Field(sa_column=Column(String(64), nullable=False))
    status: str = Field(
        default="pending",
        sa_column=Column(String(20), nullable=False, server_default="pending"),
    )
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    progress: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP"),
    )
