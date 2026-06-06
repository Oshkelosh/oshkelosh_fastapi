"""
Notification addon abstract class.

All notification integrations (email, SMS, webhooks) must inherit from
``NotificationAddon`` and implement the sending methods.
"""

from abc import abstractmethod
from typing import Any, Dict

from app.addons.base import BaseAddon


class NotificationAddon(BaseAddon):
    """Abstract base for notification-channel integrations."""

    addon_category: str = "notification"

    @abstractmethod
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
    ) -> Dict[str, Any]:
        """Send an email notification.

        Args:
            to:       Recipient email address.
            subject:  Email subject line.
            body:     Plain-text body.
            html:     When ``True``, ``body`` is treated as HTML.
        """
        ...

    @abstractmethod
    async def send_sms(self, to: str, body: str) -> Dict[str, Any]:
        """Send an SMS notification.

        Args:
            to:   Recipient phone number (E.164 format).
            body: SMS message body.
        """
        ...

    @abstractmethod
    async def send_webhook(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a POST request to a webhook URL.

        Args:
            url:     Target webhook URL.
            payload: JSON-serialisable dict to send in the request body.
        """
        ...
