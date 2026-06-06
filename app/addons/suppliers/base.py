"""
Supplier addon abstract class.

All supplier integrations (Printful, Spocket, etc.) must inherit from
``SupplierAddon`` and implement the product / order / inventory methods.
"""

from abc import abstractmethod
from typing import Any, Dict, List

from app.addons.base import BaseAddon


class SupplierAddon(BaseAddon):
    """Abstract base for product-supplier integrations."""

    addon_category: str = "supplier"

    @abstractmethod
    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Return the full product catalog from the supplier."""
        ...

    @abstractmethod
    async def get_product(self, product_id: str) -> Dict[str, Any]:
        """Fetch a single product by its supplier ID."""
        ...

    @abstractmethod
    async def create_order(
        self, product_ids: List[str], shipping_address: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a fulfillment order for the given products.

        Args:
            product_ids:        List of supplier product IDs to order.
            shipping_address:   Dict with keys like ``line1``, ``city``,
                                ``state``, ``zip``, ``country``, ``first_name``,
                                ``last_name``, ``email``.
        """
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Return the current status of a fulfillment order."""
        ...

    @abstractmethod
    async def sync_inventory(self) -> None:
        """Sync local inventory levels with the supplier's current stock."""
        ...
