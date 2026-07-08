"""
Tool addon abstract class.

Advanced shop utilities (analytics, A/B testing, SEO, etc.) inherit from
``ToolAddon``. Multiple tools may be enabled at the same time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.addons.base import BaseAddon

if TYPE_CHECKING:
    from app.services.pricing.protocols import TaxQuote

__all__ = ["TaxQuote", "ToolAddon"]


def __getattr__(name: str) -> Any:
    if name == "TaxQuote":
        from app.services.pricing.protocols import TaxQuote as tax_quote

        return tax_quote
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class ToolAddon(BaseAddon):
    """Abstract base for optional e-commerce tools and integrations."""

    addon_category: str = "tool"

    def list_public_providers(self) -> list[dict[str, str]]:
        """Return public auth provider metadata for storefront bootstrapping."""
        return []

    def supports_tax_quotes(self) -> bool:
        """Whether this tool provides third-party tax calculation at checkout."""
        return False

    async def quote_tax(
        self,
        items: list[dict[str, Any]],
        shipping_address: dict[str, Any] | None,
        subtotal_cents: int,
    ) -> TaxQuote | None:
        """Return tax cents for the cart, or None to defer to Site Settings rules."""
        return None

    async def on_lifecycle_event(
        self,
        event_key: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle lifecycle events (user.registered, order.paid, cart.abandoned)."""
        return None

    async def on_commerce_event(
        self,
        event_key: str,
        payload: dict[str, Any],
    ) -> None:
        """Handle commerce measurement events (purchase, add_to_cart, etc.)."""
        return None

    def list_storefront_scripts(self) -> list[dict[str, Any]]:
        """Return public script descriptors for storefront injection."""
        return []

    def supports_product_search(self) -> bool:
        """Whether this tool provides external product search."""
        return False

    async def search_products(
        self,
        session: Any,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict[str, Any] | None:
        """Return paginated product list payload, or None to use core ILIKE search."""
        return None
