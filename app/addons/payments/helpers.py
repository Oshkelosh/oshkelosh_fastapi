"""Shared helpers for payment addons (no PSP-specific logic)."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping

if TYPE_CHECKING:
    from models.site_settings import SiteSettings


async def verify_paid_via_refetch(
    get_status: Callable[[str], Awaitable[dict[str, Any]]],
    payment_id: str,
    paid_statuses: set[str],
) -> bool:
    """Confirm a payment is genuinely paid by re-fetching it from the provider.

    For PSPs whose webhooks carry no verifiable body signature, authenticity is
    established by looking the payment up through the authenticated provider API:
    a forged webhook body references no real (or no paid) payment and is rejected.
    Fails closed on any lookup error.

    ponytail: this defeats fully forged webhooks but not a merchant-scoped replay
    that reuses a real paid payment id with a swapped order_id; provider metadata
    binding is tracked separately.
    """
    if not payment_id:
        return False
    try:
        data = await get_status(payment_id)
    except Exception:
        return False
    return str(data.get("status", "")).strip().lower() in {s.lower() for s in paid_statuses}


def header_get(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive header lookup returning '' when absent."""
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return value
    return ""


def verify_hmac_sha256_hex(
    secret: str,
    body: bytes,
    signature: str,
    *,
    prefix: bytes = b"",
) -> bool:
    """Constant-time compare of a hex HMAC-SHA256 of ``prefix + body``.

    Used by PSPs whose webhook signature is a plain hex HMAC of the request body
    (e.g. Checkout.com ``Cko-Signature``), optionally with a signed timestamp
    prefix (e.g. Airwallex ``x-timestamp`` + body). Fails closed on missing inputs.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), prefix + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def verify_stripe_signature(secret: str, body: bytes, header: str) -> bool:
    """Verify a Stripe ``Stripe-Signature`` header (``t=..,v1=..``).

    Replay of a *previously processed* event is already blocked by the unique
    ``ProcessedWebhookEvent.event_id`` record, so no timestamp tolerance is enforced
    here. ponytail: add a timestamp window if replay of never-seen events matters.
    """
    if not secret or not header:
        return False
    timestamp = ""
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    signed_payload = f"{timestamp}.".encode("utf-8") + body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig.strip()) for sig in signatures)


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
    """Fake checkout session — ONLY for the missing-credentials/dev case.

    Never return this on a live API error: a fake success URL makes checkout
    look like it worked while no payment exists. Use ``create_payment_error``.
    """
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


def create_payment_error(provider: str, exc: Exception, order_id: str) -> dict[str, Any]:
    """Uniform failure result for create_payment API errors."""
    return {
        "success": False,
        "error": str(exc),
        "provider": provider,
        "order_id": order_id,
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
