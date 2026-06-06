"""
Frontend addon abstract class.

Each frontend is a pre-built SPA bundle plus frontend-specific configuration.
Site-wide branding comes from ``SiteSettings``, not the frontend addon schema.
"""

from abc import abstractmethod

from app.addons.base import BaseAddon


class FrontendAddon(BaseAddon):
    """Abstract base for interchangeable storefront SPAs."""

    addon_category: str = "frontend"

    def api_mount_prefix(self) -> str:
        return f"/frontends/{self.addon_id}"

    def admin_mount_prefix(self) -> str:
        return f"/frontends/{self.addon_id}"

    @abstractmethod
    def get_static_directory(self) -> str:
        """Filesystem path to the built SPA (must contain ``index.html``)."""
        ...
