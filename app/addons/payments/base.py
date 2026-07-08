"""
Payment addon abstract class.

All payment integrations (Stripe, PayPal, etc.) must inherit from
``PaymentAddon`` and implement the payment lifecycle methods.
"""

from abc import abstractmethod
from typing import Any, Dict

from app.addons.base import BaseAddon
from schemas.payment import PaymentWebhookOutcome


class PaymentAddon(BaseAddon):
    """Abstract base for payment-gateway integrations."""

    addon_category: str = "payment"

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
    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        """Mark a payment as confirmed / captured."""
        ...

    @abstractmethod
    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        """Refund a payment (full or partial)."""
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

    async def handle_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> Dict[str, Any]:
        """Legacy adapter — prefer ``parse_webhook``."""
        outcome = await self.parse_webhook(payload, signature)
        return {
            "handled": outcome.handled,
            "event_type": outcome.event_type,
            "event_id": outcome.event_id,
            "error": outcome.error,
        }

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
