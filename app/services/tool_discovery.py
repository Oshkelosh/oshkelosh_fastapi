"""Aggregate enabled tool addons for storefront and commerce hooks."""

from __future__ import annotations

import logging
from typing import Any

from app.services.addons import get_enabled_tools

logger = logging.getLogger(__name__)


def list_storefront_scripts() -> list[dict[str, Any]]:
    """Collect script injection metadata from all enabled tools."""
    scripts: list[dict[str, Any]] = []
    for tool in get_enabled_tools():
        try:
            entries = tool.list_storefront_scripts()
        except Exception:
            logger.exception("Tool '%s' list_storefront_scripts failed", tool.addon_id)
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id"):
                scripts.append(entry)
    return scripts


async def dispatch_commerce_event(
    event_key: str,
    payload: dict[str, Any],
) -> None:
    """Notify enabled tools of a commerce measurement event (e.g. purchase)."""
    for tool in get_enabled_tools():
        try:
            await tool.on_commerce_event(event_key, payload)
        except Exception:
            logger.exception(
                "Tool '%s' failed handling commerce event '%s'",
                tool.addon_id,
                event_key,
            )


def build_purchase_payload(order: Any, user: Any | None = None) -> dict[str, Any]:
    from app.services.lifecycle_events import build_order_paid_payload

    return build_order_paid_payload(order, user)
