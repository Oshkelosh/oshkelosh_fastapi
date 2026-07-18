"""
Notification addon abstract class.

All notification integrations (email, SMS, push, webhooks) must inherit from
``NotificationAddon`` and implement the sending methods for their channel(s).
"""

from abc import abstractmethod
from typing import Any, ClassVar, Dict

from app.addons.base import BaseAddon


class NotificationAddon(BaseAddon):
    """Abstract base for notification-channel integrations."""

    addon_category: str = "notification"
    supported_channels: ClassVar[list[str]] = ["email"]

    @abstractmethod
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
    ) -> Dict[str, Any]:
        """Send an email notification."""
        ...

    @abstractmethod
    async def send_sms(self, to: str, body: str) -> Dict[str, Any]:
        """Send an SMS notification."""
        ...

    @abstractmethod
    async def send_push(
        self,
        to: str,
        title: str,
        body: str,
        data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Send a push notification to a device token or provider user id."""
        ...

    async def send_webhook(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST JSON to a merchant-configured webhook URL (SSRF-guarded)."""
        from app.addons.log import label_for, warning
        from app.addons.notifications.helpers import post_json_webhook

        result = await post_json_webhook(url, payload)
        if not result.get("success"):
            warning(label_for(self), "send_webhook to={} error: {}", url, result.get("error"))
        return result

    def list_public_push_config(self) -> dict[str, Any] | None:
        """Return public web push client config for the storefront, or None."""
        return None

    def push_service_worker_js(self) -> str | None:
        """Return provider-specific JS for the root-scope web-push service worker.

        Core serves this verbatim from its service-worker routes; return None
        when the addon needs no service worker (or is not configured).
        """
        return None

    @classmethod
    def channel_not_supported(cls, channel: str, to: str = "") -> Dict[str, Any]:
        return {
            "success": False,
            "message_id": "",
            "error": f"{channel} not supported by {cls.addon_id}",
            "to": to,
        }
