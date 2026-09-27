"""Outbound HMAC-signed webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlmodel import select

from app.core.exceptions import ValidationError
from app.db.base import utc_now
from models.outbound_webhook_endpoint import OutboundWebhookEndpoint

logger = logging.getLogger(__name__)

_SINGLETON_ID = 1
_HTTP_TIMEOUT = 5.0
_MAX_ERROR_LEN = 500

EVENT_ORDER_PLACED = "order.placed"
EVENT_ORDER_PAID = "order.paid"
EVENT_ORDER_SHIPPED = "order.shipped"
EVENT_ORDER_DELIVERED = "order.delivered"
EVENT_ORDER_CANCELLED = "order.cancelled"
EVENT_USER_REGISTERED = "user.registered"
EVENT_CART_ABANDONED = "cart.abandoned"
EVENT_WEBHOOK_TEST = "webhook.test"

SELECTABLE_EVENTS: tuple[tuple[str, str], ...] = (
    (EVENT_ORDER_PLACED, "Order placed"),
    (EVENT_ORDER_PAID, "Order paid"),
    (EVENT_ORDER_SHIPPED, "Order shipped"),
    (EVENT_ORDER_DELIVERED, "Order delivered"),
    (EVENT_ORDER_CANCELLED, "Order cancelled"),
    (EVENT_USER_REGISTERED, "User registered"),
    (EVENT_CART_ABANDONED, "Cart abandoned"),
)

SELECTABLE_EVENT_KEYS = frozenset(key for key, _label in SELECTABLE_EVENTS)

_STATUS_EVENT_MAP: dict[tuple[str, str], str] = {
    ("pending", "paid"): EVENT_ORDER_PAID,
    ("paid", "shipped"): EVENT_ORDER_SHIPPED,
    ("shipped", "delivered"): EVENT_ORDER_DELIVERED,
}

HEADER_ID = "X-Webhook-Id"
HEADER_TIMESTAMP = "X-Webhook-Timestamp"
HEADER_EVENT = "X-Webhook-Event"
HEADER_SIGNATURE = "X-Webhook-Signature"


def generate_webhook_secret() -> str:
    """Return a new core-generated signing secret."""
    return secrets.token_urlsafe(32)


def mask_webhook_secret(secret: str | None) -> str:
    """Return a display mask that never includes the full secret."""
    if not secret:
        return ""
    return f"••••{secret[-4:]}" if len(secret) >= 4 else "••••"


def validate_webhook_url(url: str) -> str:
    """Require an absolute http(s) URL."""
    trimmed = url.strip()
    parsed = urlparse(trimmed)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValidationError(message="Webhook URL must be an absolute http(s) URL")
    return trimmed


def sign_webhook_payload(secret: str, timestamp: str, body: bytes) -> str:
    """Return ``t=<ts>,v1=<hex>`` HMAC-SHA256 of ``{timestamp}.{raw_body}``."""
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_webhook_signature(secret: str, timestamp: str, body: bytes, header: str) -> bool:
    """Constant-time compare of a signature header produced by ``sign_webhook_payload``."""
    if not secret or not header:
        return False
    expected = sign_webhook_payload(secret, timestamp, body)
    return hmac.compare_digest(expected, header.strip())


def build_order_webhook_payload(order: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "order_id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "total_cents": order.total_cents,
        "tax_cents": order.tax_cents,
        "shipping_cents": order.shipping_cents,
        "currency": order.currency,
    }
    tracking_number = getattr(order, "tracking_number", None)
    tracking_url = getattr(order, "tracking_url", None)
    carrier = getattr(order, "carrier", None)
    if tracking_number:
        payload["tracking_number"] = tracking_number
    if tracking_url:
        payload["tracking_url"] = tracking_url
    if carrier:
        payload["carrier"] = carrier
    return payload


def endpoint_to_dict(row: OutboundWebhookEndpoint) -> dict[str, Any]:
    """Serialize config for audit (secret key name is redacted by audit helpers)."""
    return {
        "enabled": bool(row.enabled),
        "url": row.url,
        "secret": row.secret,
        "events": list(row.events or []),
    }


async def get_outbound_webhook_endpoint(session: Any) -> OutboundWebhookEndpoint:
    """Return the singleton receiver row, creating it if missing."""
    result = await session.execute(
        select(OutboundWebhookEndpoint).where(OutboundWebhookEndpoint.id == _SINGLETON_ID)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    row = OutboundWebhookEndpoint(id=_SINGLETON_ID, enabled=False, events=[])
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def save_outbound_webhook_endpoint(
    session: Any,
    *,
    enabled: bool,
    url: str,
    events: list[str],
) -> tuple[OutboundWebhookEndpoint, str | None]:
    """Persist URL/events/enabled. Generate a secret on first save. Never overwrite an existing secret."""
    row = await get_outbound_webhook_endpoint(session)
    cleaned_url = validate_webhook_url(url) if url.strip() else None
    if enabled and not cleaned_url:
        raise ValidationError(message="A webhook URL is required when the receiver is enabled")
    selected = [key for key in events if key in SELECTABLE_EVENT_KEYS]
    row.enabled = bool(enabled)
    row.url = cleaned_url
    row.events = selected
    row.updated_at = utc_now()
    revealed: str | None = None
    if not row.secret:
        revealed = generate_webhook_secret()
        row.secret = revealed
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    await session.flush()
    await session.refresh(row)
    return row, revealed


async def rotate_outbound_webhook_secret(session: Any) -> tuple[OutboundWebhookEndpoint, str]:
    """Replace the signing secret and return the new value (show once)."""
    row = await get_outbound_webhook_endpoint(session)
    revealed = generate_webhook_secret()
    row.secret = revealed
    row.updated_at = utc_now()
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    await session.flush()
    await session.refresh(row)
    return row, revealed


def _encode_envelope(event_type: str, data: dict[str, Any]) -> tuple[str, str, bytes, dict[str, str]]:
    delivery_id = str(uuid.uuid4())
    timestamp = str(int(datetime.now(tz=UTC).timestamp()))
    envelope = {
        "id": delivery_id,
        "type": event_type,
        "created": int(timestamp),
        "data": data,
    }
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return delivery_id, timestamp, body, envelope  # type: ignore[return-value]


async def _record_delivery_result(
    session: Any,
    row: OutboundWebhookEndpoint,
    *,
    status_code: int | None,
    error: str | None,
) -> None:
    row.last_status = status_code
    row.last_error = (error or "")[:_MAX_ERROR_LEN] or None
    row.last_sent_at = utc_now()
    row.updated_at = utc_now()
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(row)
    try:
        await session.flush()
    except Exception:
        logger.exception("Failed to persist outbound webhook delivery status")


async def emit_outbound_webhook(
    session: Any,
    event_type: str,
    data: dict[str, Any],
    *,
    force: bool = False,
) -> bool:
    """POST a signed event. Never raises. ``force`` is for webhook.test pings."""
    try:
        row = await get_outbound_webhook_endpoint(session)
    except Exception:
        logger.exception("Failed to load outbound webhook endpoint")
        return False

    if not row.url or not row.secret:
        return False
    if not force:
        if not row.enabled:
            return False
        if event_type not in (row.events or []):
            return False
    elif event_type != EVENT_WEBHOOK_TEST:
        return False

    delivery_id, timestamp, body, _envelope = _encode_envelope(event_type, data)
    headers = {
        HEADER_ID: delivery_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_EVENT: event_type,
        HEADER_SIGNATURE: sign_webhook_payload(row.secret, timestamp, body),
        "Content-Type": "application/json",
        "User-Agent": "Oshkelosh-Webhook/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(row.url, content=body, headers=headers)
        await _record_delivery_result(session, row, status_code=response.status_code, error=None)
        if response.status_code >= 400:
            logger.warning(
                "Outbound webhook %s returned HTTP %s",
                event_type,
                response.status_code,
            )
        return 200 <= response.status_code < 300
    except Exception as exc:
        logger.warning("Outbound webhook %s delivery failed: %s", event_type, exc)
        await _record_delivery_result(session, row, status_code=None, error=str(exc))
        return False


async def emit_order_status_webhook(session: Any, order: Any, old_status: str, new_status: str) -> None:
    """Emit the matching order.* event after a status transition."""
    event_type = _STATUS_EVENT_MAP.get((old_status, new_status))
    if event_type is None and new_status == "cancelled":
        event_type = EVENT_ORDER_CANCELLED
    if event_type is None:
        return
    await emit_outbound_webhook(session, event_type, build_order_webhook_payload(order))


async def send_outbound_webhook_test(session: Any) -> bool:
    """POST webhook.test to the saved URL. Requires URL + secret; ignores enabled/events."""
    return await emit_outbound_webhook(
        session,
        EVENT_WEBHOOK_TEST,
        {"ok": True, "message": "Oshkelosh webhook test"},
        force=True,
    )
