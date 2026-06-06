"""
Payment addon abstract class.

All payment integrations (Stripe, PayPal, etc.) must inherit from
``PaymentAddon`` and implement the payment lifecycle methods.
"""

from abc import abstractmethod
from typing import Any, Dict

from app.addons.base import BaseAddon


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
    ) -> Dict[str, Any]:
        """Create a new payment / checkout session.

        Args:
            amount:         Amount in smallest currency unit (e.g. cents).
            currency:       ISO 4217 currency code (e.g. ``"usd"``).
            order_id:       Local order identifier.
            customer_email: Customer email for the invoice.
        """
        ...

    @abstractmethod
    async def confirm_payment(self, payment_id: str) -> Dict[str, Any]:
        """Mark a payment as confirmed / captured."""
        ...

    @abstractmethod
    async def refund_payment(self, payment_id: str, amount: int) -> Dict[str, Any]:
        """Refund a payment (full or partial).

        Args:
            payment_id: ID of the payment to refund.
            amount:     Refund amount in smallest currency unit.
        """
        ...

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Return the current status of a payment."""
        ...

    @abstractmethod
    async def handle_webhook(
        self, payload: Dict[str, Any], signature: str
    ) -> Dict[str, Any]:
        """Process an incoming webhook event from the payment provider.

        Returns a dict with ``"handled"`` (bool) and ``"event"`` metadata.
        """
        ...
