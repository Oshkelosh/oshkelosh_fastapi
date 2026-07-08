"""Shared helpers for payment addons (no PSP-specific logic)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models.site_settings import SiteSettings


def resolve_storefront_base_url(
    site_settings: SiteSettings | None = None,
    *,
    request=None,
) -> str:
    """Resolve the public storefront base URL for checkout redirects."""
    from app.services.site_settings import resolve_public_site_url

    return resolve_public_site_url(site_settings=site_settings, request=request)


def build_checkout_redirect_urls(
    site_settings: SiteSettings | None,
    order_id: str | int,
    *,
    request=None,
) -> tuple[str, str]:
    """Build per-order success and cancel URLs for hosted checkout."""
    base = resolve_storefront_base_url(site_settings, request=request)
    oid = str(order_id)
    return (
        f"{base}/orders/{oid}?payment=return",
        f"{base}/checkout",
    )


def effective_redirect_url(configured: str | None, *, fallback: str) -> str:
    """Use addon config override when set; otherwise use core-computed fallback."""
    if configured and configured.strip():
        return configured.strip()
    return fallback


def mock_checkout(
    provider: str,
    order_id: str,
    amount: int,
    currency: str,
) -> dict[str, Any]:
    payment_id = f"mock_pay_{uuid.uuid4().hex[:12]}"
    return {
        "success": True,
        "payment_id": payment_id,
        "session_id": payment_id,
        "url": f"https://checkout.{provider}.example/mock/{order_id}",
        "order_id": order_id,
        "amount": amount,
        "currency": currency,
        "note": f"Mock session ({provider} credentials not configured)",
    }


def extract_order_id(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    raw = metadata.get("order_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
