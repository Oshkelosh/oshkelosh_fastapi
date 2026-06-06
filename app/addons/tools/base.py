"""
Tool addon abstract class.

Advanced shop utilities (analytics, A/B testing, SEO, etc.) inherit from
``ToolAddon``. Multiple tools may be enabled at the same time.
"""

from app.addons.base import BaseAddon


class ToolAddon(BaseAddon):
    """Abstract base for optional e-commerce tools and integrations."""

    addon_category: str = "tool"
