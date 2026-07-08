"""Load, render, and persist notification message templates."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlmodel import col, select

from app.services.notification_events import (
    NOTIFICATION_EVENTS,
    NotificationChannel,
    get_event,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@dataclass
class RenderedNotification:
    subject: str
    body: str


def _safe_format(template: str, context: dict[str, Any]) -> str:
    """Replace {key} placeholders; leave unknown keys as-is."""

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            return match.group(0)
        value = context[key]
        return "" if value is None else str(value)

    return _PLACEHOLDER_RE.sub(replacer, template)


def default_template(event_key: str, channel: NotificationChannel) -> tuple[str, str]:
    event = get_event(event_key)
    if event is None:
        raise ValueError(f"Unknown notification event: {event_key}")
    if channel not in event.channels:
        raise ValueError(f"Channel {channel} not supported for {event_key}")
    return event.default_subject, event.default_body


async def get_template_row(session: Any, event_key: str, channel: str) -> Any | None:
    from models.notification_template import NotificationTemplate

    result = await session.execute(
        select(NotificationTemplate).where(
            col(NotificationTemplate.event_key) == event_key,
            col(NotificationTemplate.channel) == channel,
        )
    )
    return result.scalar_one_or_none()


async def get_effective_template(
    session: Any,
    event_key: str,
    channel: NotificationChannel,
) -> tuple[str, str, bool]:
    """Return (subject, body, is_enabled). Falls back to event defaults."""
    row = await get_template_row(session, event_key, channel)
    if row is not None:
        return row.subject, row.body, row.is_enabled
    subject, body = default_template(event_key, channel)
    return subject, body, True


async def render_notification(
    session: Any,
    event_key: str,
    channel: NotificationChannel,
    context: dict[str, Any],
    *,
    store_prefix: str = "",
) -> RenderedNotification | None:
    """Render template for an event/channel; None when disabled or missing event."""
    if get_event(event_key) is None:
        return None

    subject, body, enabled = await get_effective_template(session, event_key, channel)
    if not enabled:
        return None

    rendered_subject = _safe_format(subject, context)
    rendered_body = _safe_format(body, context)
    if store_prefix and channel in ("email", "push"):
        rendered_subject = f"{store_prefix}{rendered_subject}"
    return RenderedNotification(subject=rendered_subject, body=rendered_body)


async def save_template(
    session: Any,
    event_key: str,
    channel: str,
    *,
    subject: str,
    body: str,
    is_enabled: bool,
) -> Any:
    from models.notification_template import NotificationTemplate

    if get_event(event_key) is None:
        raise ValueError(f"Unknown notification event: {event_key}")

    row = await get_template_row(session, event_key, channel)
    if row is None:
        row = NotificationTemplate(
            event_key=event_key,
            channel=channel,
            subject=subject,
            body=body,
            is_enabled=is_enabled,
        )
        session.add(row)
    else:
        row.subject = subject
        row.body = body
        row.is_enabled = is_enabled
        if hasattr(session, "mark_dirty"):
            session.mark_dirty(row)
    await session.flush()
    return row


async def reset_template(session: Any, event_key: str, channel: str) -> None:
    row = await get_template_row(session, event_key, channel)
    if row is not None:
        await session.delete(row)
        await session.flush()


async def seed_default_templates(session: Any) -> None:
    """Insert DB rows for defaults when table is empty (idempotent)."""
    from models.notification_template import NotificationTemplate

    result = await session.execute(select(NotificationTemplate).limit(1))
    if result.scalar_one_or_none() is not None:
        return

    for event in NOTIFICATION_EVENTS.values():
        for channel in event.channels:
            session.add(
                NotificationTemplate(
                    event_key=event.key,
                    channel=channel,
                    subject=event.default_subject,
                    body=event.default_body,
                    is_enabled=True,
                )
            )
    await session.flush()
    logger.info("Seeded default notification templates")
