"""
Supplier addon abstract class.

All supplier integrations (Printful, Spocket, etc.) must inherit from
``SupplierAddon`` and implement the product / order / inventory methods.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar, Dict, List

from app.addons.base import BaseAddon
from schemas.supplier import SupplierAssignment, SupplierCatalogProduct, SupplierOption


class SupplierAddon(BaseAddon):
    """Abstract base for product-supplier integrations."""

    addon_category: str = "supplier"
    requires_variant_id: ClassVar[bool] = False
    requires_product_id: ClassVar[bool] = True

    def supports_catalog_sync(self) -> bool:
        """Whether this addon can import a remote catalog into local products."""
        return True

    def export_config_updates(self) -> dict[str, Any]:
        """Return config fields to persist after runtime API calls (e.g. OAuth tokens)."""
        return {}

    def admin_form_hints(self) -> dict[str, str | bool]:
        """Metadata for the admin product form (variant field visibility, help text)."""
        if self.requires_variant_id:
            product_help = f"Required. {self.addon_name} product ID."
            variant_help = f"Required. {self.addon_name} variant ID."
        else:
            product_help = f"Required. {self.addon_name} supplier product ID."
            variant_help = ""
        return {
            "requires_variant_id": self.requires_variant_id,
            "product_id_help": product_help,
            "variant_id_help": variant_help,
        }

    def admin_form_meta_key(self) -> str:
        """Key used in admin product-form metadata (dropdown value or prefix)."""
        return self.addon_id

    def assignment_from_variant(self, variant: Any) -> SupplierAssignment | None:
        """Build a supplier assignment from a product variant row's supplier fields."""
        product_id = variant.supplier_product_id or ""
        variant_id = variant.supplier_variant_id
        if not product_id and not variant_id:
            return None
        return SupplierAssignment(
            addon_id=self.addon_id,
            supplier_product_id=str(product_id),
            variant_id=str(variant_id) if variant_id else None,
        )

    def variant_fields_from_form(
        self,
        supplier_value: str,
        supplier_product_id: str = "",
        supplier_variant_id: str = "",
    ) -> tuple[str | None, str | None]:
        """Map admin product-form values to (supplier_product_id, supplier_variant_id) refs."""
        del supplier_value
        return supplier_product_id.strip() or None, supplier_variant_id.strip() or None

    def has_dedicated_admin_page(self) -> bool:
        """Whether the addon manages itself on its own admin page (hidden from the generic list)."""
        return False

    def parse_assignment(self, tag: dict[str, Any]) -> SupplierAssignment | None:
        """Parse a product tag dict into a supplier assignment for this addon."""
        if not isinstance(tag, dict):
            return None
        addon_id = tag.get("supplier_addon_id")
        if str(addon_id) != self.addon_id:
            return None

        manual_slug = tag.get("manual_supplier_slug") or tag.get("supplier_ref")
        manual_slug = str(manual_slug) if manual_slug else None
        variant_id = tag.get("supplier_variant_id")
        variant_id = str(variant_id) if variant_id else None
        product_id = tag.get("supplier_product_id")

        if self.requires_variant_id:
            if not product_id or not variant_id:
                return None
            product_id = str(product_id)
        elif self.requires_product_id:
            if not product_id:
                return None
            product_id = str(product_id)
        else:
            product_id = str(product_id) if product_id else ""

        return SupplierAssignment(
            addon_id=self.addon_id,
            supplier_product_id=product_id,
            manual_slug=manual_slug,
            variant_id=variant_id,
        )

    def build_tag_from_form(
        self,
        supplier_value: str,
        supplier_product_id: str = "",
        supplier_variant_id: str = "",
    ) -> dict[str, str] | None:
        """Build a supplier tag from admin form values."""
        if supplier_value != self.addon_id:
            return None

        product_id = supplier_product_id.strip()
        variant_id = supplier_variant_id.strip()

        if self.requires_variant_id:
            if not product_id or not variant_id:
                return None
            tag: dict[str, str] = {
                "supplier_addon_id": self.addon_id,
                "supplier_product_id": product_id,
                "supplier_variant_id": variant_id,
            }
            return tag

        if self.requires_product_id and not product_id:
            return None

        tag = {"supplier_addon_id": self.addon_id}
        if product_id:
            tag["supplier_product_id"] = product_id
        return tag

    def validate_admin_form(
        self,
        supplier_value: str,
        supplier_product_id: str = "",
        supplier_variant_id: str = "",
    ) -> str | None:
        """Return an error message if admin form fields are invalid, else None."""
        if supplier_value != self.addon_id:
            return f"Invalid supplier selection for {self.addon_name}."

        product_id = supplier_product_id.strip()
        variant_id = supplier_variant_id.strip()

        if self.requires_variant_id:
            if not product_id or not variant_id:
                return f"{self.addon_name} product ID and variant ID are required."
            return None

        if self.requires_product_id and not product_id:
            return f"{self.addon_name} product ID is required."
        return None

    def external_key_from_assignment(self, assignment: SupplierAssignment) -> str | None:
        """Stable catalog sync key derived from a supplier assignment."""
        if assignment.addon_id != self.addon_id:
            return None
        if not assignment.supplier_product_id:
            return None
        if self.requires_variant_id:
            if not assignment.variant_id:
                return None
            return (
                f"{self.addon_id}:{assignment.supplier_product_id}:{assignment.variant_id}"
            )
        return f"{self.addon_id}:{assignment.supplier_product_id}"

    def fulfillment_key(self, assignment: SupplierAssignment) -> str:
        """Unique key for grouping line items by supplier destination."""
        return self.addon_id

    def assignment_dropdown_value(self, assignment: SupplierAssignment) -> str:
        """Admin product-form dropdown value for an existing assignment."""
        return self.addon_id

    def assignment_display_label(self, assignment: SupplierAssignment) -> str:
        """Human-readable label for an assignment."""
        if assignment.manual_slug:
            return f"{self.addon_name}: {assignment.manual_slug}"
        return self.addon_name

    def lists_options_when_disabled(self) -> bool:
        """Whether ``list_admin_options`` applies when the addon is disabled."""
        return False

    def supports_shipping_quotes(self) -> bool:
        """Whether this supplier can quote shipping for checkout."""
        return False

    async def quote_shipping(
        self,
        items: list[dict[str, Any]],
        shipping_address: dict[str, Any],
        *,
        currency: str | None = None,
    ) -> int | None:
        """Return shipping cents for this fulfillment group, or None for Site Settings."""
        del currency
        return None

    async def quote_shipping_details(
        self,
        items: list[dict[str, Any]],
        shipping_address: dict[str, Any],
        *,
        selected_id: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any] | None:
        """Return ``{cents, selected_id, options}`` or None to fall back to quote_shipping.

        ``options`` entries: ``{id, name, cents}`` plus optional delivery fields.
        """
        del selected_id
        amount = await self.quote_shipping(
            items, shipping_address, currency=currency
        )
        if amount is None:
            return None
        return {"cents": int(amount), "selected_id": None, "options": []}

    async def list_admin_options(self, session: Any) -> list[SupplierOption]:
        """Return dropdown options for the admin product form."""
        return [
            SupplierOption(
                value=self.addon_id,
                label=self.addon_name,
                addon_id=self.addon_id,
            )
        ]

    @abstractmethod
    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Return the full product catalog from the supplier."""
        ...

    async def fetch_catalog_for_import(self, **kwargs: Any) -> List[SupplierCatalogProduct]:
        """Fetch remote catalog and return normalized products with variants."""
        raise NotImplementedError(
            f"Supplier addon '{self.addon_id}' does not implement catalog import"
        )

    @abstractmethod
    async def get_product(self, product_id: str) -> Dict[str, Any]:
        """Fetch a single product by its supplier ID."""
        ...

    @abstractmethod
    async def create_order(
        self,
        items: List[Dict[str, Any]],
        shipping_address: Dict[str, Any],
        *,
        external_id: str | None = None,
        supplier_ref: str | None = None,
        shipping_method: str | None = None,
        currency: str | None = None,
    ) -> Dict[str, Any]:
        """Create a fulfillment order for the given products.

        Args:
            items:              Line items with ``supplier_product_id``,
                                ``quantity``, and optional ``product_name``.
            shipping_address:   Dict with keys like ``line1``, ``city``,
                                ``state``, ``zip``, ``country``, ``first_name``,
                                ``last_name``, ``email``.
            external_id:        Oshkelosh order id for provider reference.
            supplier_ref:       Manual supplier slug when ``addon_id`` is
                                ``manual``.
            shipping_method:    Customer-selected shipping method key, when the
                                supplier supports method selection.
            currency:           ISO currency of the order; ignore if the
                                supplier bills in a fixed currency.

        Implementations must accept all keyword arguments (ignore what they
        don't use) so core can call every supplier uniformly.
        """
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Return the current status of a fulfillment order."""
        ...
