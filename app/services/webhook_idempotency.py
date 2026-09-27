"""Shared webhook event claim helper (provider-agnostic)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

from models.processed_webhook_event import ProcessedWebhookEvent


async def claim_webhook_event(
    session: Any,
    *,
    event_id: str,
    provider: str,
    event_type: str = "processing",
) -> bool:
    """Insert a processed-webhook row. Return False when the event was already claimed."""
    record = ProcessedWebhookEvent(
        event_id=event_id,
        provider=provider,
        event_type=event_type,
    )
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError:
        return False
    return True
