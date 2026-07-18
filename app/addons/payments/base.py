"""
Payment addon abstract class.

All payment integrations (Stripe, PayPal, etc.) must inherit from
``PaymentAddon`` and implement the payment lifecycle methods.
"""

from abc import abstractmethod
from typing import Any, Dict, Mapping

from app.addons.base import BaseAddon
from schemas.payment import PaymentWebhookOutcome


class PaymentAddon(BaseAddon):
    """Abstract base for payment-gateway integrations."""

    addon_category: str = "payment"

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Return True only when the webhook is provably from the provider.

        Fails closed: the default rejects everything. Each payment addon MUST
        override this to verify the provider signature (HMAC, verify API, etc.)
        before core will mark any order paid. An addon that cannot verify a
        webhook must return False rather than trusting the body.
        """
        del headers, body
        return False

    @abstractmethod
    async def create_payment(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        *,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Dict[str, Any]:
        """Create a new payment / checkout session."""
        ...

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Return the current status of a payment."""
        ...

    @abstractmethod
    async def parse_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> PaymentWebhookOutcome:
        """Parse a provider webhook into a structured outcome (no DB writes)."""
        ...

    def webhook_event_id(self, payload: Dict[str, Any]) -> str:
        """Extract a stable event id from a provider payload."""
        for key in ("id", "event_id", "notificationId"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data", {})
        if isinstance(data, dict):
            for key in ("id", "payment_id", "session_id"):
                value = data.get(key)
                if value:
                    return str(value)
        return ""

    def webhook_signature_header(self) -> str:
        """Default HTTP header name for webhook signatures."""
        return "signature"
