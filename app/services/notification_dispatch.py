"""Dispatch rendered notifications to channel-specific addons."""

from __future__ import annotations

import logging
from typing import Any

from app.services.addons import get_notification_addon_for_channel
from app.services.notification_events import NotificationChannel, event_supports_channel
from app.services.notification_templates import render_notification
from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)


async def dispatch_notification(
    session: Any,
    event_key: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    push_token: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Send notification on all applicable enabled channels."""
    ctx = dict(context or {})
    site = await get_site_settings(session)
    if site.store_name and "store_name" not in ctx:
        ctx["store_name"] = site.store_name
    store_prefix = f"[{site.store_name}] " if site.store_name else ""

    channels: list[tuple[NotificationChannel, str | None]] = [
        ("email", email),
        ("sms", phone),
        ("push", push_token),
    ]

    for channel, recipient in channels:
        if not recipient or not event_supports_channel(event_key, channel):
            continue

        rendered = await render_notification(
            session,
            event_key,
            channel,
            ctx,
            store_prefix=store_prefix,
        )
        if rendered is None:
            continue

        addon = get_notification_addon_for_channel(channel)
        if addon is None:
            logger.debug("No %s notification addon enabled; skipping %s", channel, event_key)
            continue

        try:
            if channel == "email":
                result = await addon.send_email(recipient, rendered.subject, rendered.body)
            elif channel == "sms":
                result = await addon.send_sms(recipient, rendered.body)
            else:
                result = await addon.send_push(
                    recipient,
                    rendered.subject,
                    rendered.body,
                    data={"event": event_key, **ctx},
                )
            if not result.get("success", True):
                logger.warning(
                    "Notification %s/%s to %s failed: %s",
                    event_key,
                    channel,
                    recipient,
                    result.get("error", "unknown"),
                )
        except Exception:
            logger.exception(
                "Notification addon error for %s/%s to %s",
                event_key,
                channel,
                recipient,
            )
