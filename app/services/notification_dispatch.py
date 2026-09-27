"""Dispatch rendered notifications to channel-specific addons."""

from __future__ import annotations

import logging
from typing import Any

from app.services.addons import get_notification_addon_for_channel
from app.services.notification_events import NotificationChannel, event_supports_channel
from app.services.notification_templates import render_notification
from app.services.site_settings import get_site_settings

logger = logging.getLogger(__name__)


def _notification_succeeded(result: Any) -> bool:
    """Require explicit addon success instead of treating missing keys as success."""
    return isinstance(result, dict) and result.get("success") is True


def _push_data(event_key: str, ctx: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"event": event_key}
    order_id = ctx.get("order_id")
    if order_id is not None:
        data["order_id"] = order_id
    return data


async def dispatch_notification(
    session: Any,
    event_key: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    push_token: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Send notification on all applicable enabled channels.

    Returns True when at least one channel reports explicit success.
    """
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

    any_success = False
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
                    data=_push_data(event_key, ctx),
                )
            if not _notification_succeeded(result):
                logger.warning(
                    "Notification %s/%s failed: %s",
                    event_key,
                    channel,
                    result.get("error", "missing explicit success flag")
                    if isinstance(result, dict)
                    else "invalid addon response",
                )
            else:
                any_success = True
        except Exception:
            logger.exception(
                "Notification addon error for %s/%s",
                event_key,
                channel,
            )
    return any_success
