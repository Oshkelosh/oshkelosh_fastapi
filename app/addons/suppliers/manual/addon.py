"""
Manual supplier integration.

Merchants define named suppliers in admin; paid orders produce structured
fulfillment instructions instead of calling an external API.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.addons.suppliers.base import SupplierAddon
from schemas.supplier import SupplierAssignment, SupplierOption
from app.addons.log import info
from app.addons.config_serialization import dump_addon_config

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


class ManualSupplierConfig(BaseModel):
    """Configuration for the manual supplier addon."""

    is_active: bool = Field(default=True, description="Whether manual fulfillment is active")

    @classmethod
    def config_model(cls):
        return cls


def normalize_manual_slug(value: str) -> str:
    """Normalize user input to a URL-safe slug."""
    slug = value.strip().lower().replace(" ", "_").replace("-", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    if not slug or not _SLUG_RE.match(slug):
        raise ValueError("Slug must contain only lowercase letters, digits, and underscores")
    return slug


class ManualSupplierAddon(SupplierAddon):
    """Built-in supplier for merchant-defined manual fulfillment."""

    requires_product_id = False

    def supports_catalog_sync(self) -> bool:
        return False

    addon_id: str = "manual"
    addon_name: str = "Manual suppliers"
    addon_description: str = "Fulfill orders through admin-defined suppliers without an external API."
    addon_category: str = "supplier"
    version: str = "1.0.0"
    log_label: str = "Manual"

    _config: Dict[str, Any] | None = None

    @classmethod
    def config_schema(cls):
        return ManualSupplierConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self.is_enabled = validated.is_active
        info("Manual", "Supplier addon initialized")

    async def shutdown(self) -> None:
        self._config = None
        self.is_enabled = False

    def admin_form_hints(self) -> dict[str, str | bool]:
        return {
            "requires_variant_id": False,
            "product_id_help": "Optional SKU or internal reference for this manual supplier.",
            "variant_id_help": "",
        }

    def admin_form_meta_key(self) -> str:
        return "manual:"

    def assignment_from_variant(self, variant: Any) -> SupplierAssignment | None:
        manual_slug = (
            variant.supplier_variant_id
            or (variant.attributes or {}).get("manual_supplier_slug")
        )
        return SupplierAssignment(
            addon_id=self.addon_id,
            supplier_product_id=variant.supplier_product_id or "",
            manual_slug=str(manual_slug) if manual_slug else None,
            variant_id=None,
        )

    def variant_fields_from_form(
        self,
        supplier_value: str,
        supplier_product_id: str = "",
        supplier_variant_id: str = "",
    ) -> tuple[str | None, str | None]:
        # The manual slug rides in the dropdown value ("manual:<slug>") and is
        # stored in the variant's supplier_variant_id column.
        slug = supplier_value.partition(":")[2].strip()
        return (
            supplier_product_id.strip() or None,
            slug or (supplier_variant_id.strip() or None),
        )

    def has_dedicated_admin_page(self) -> bool:
        return True

    def parse_assignment(self, tag: dict[str, Any]) -> SupplierAssignment | None:
        if not isinstance(tag, dict):
            return None
        if str(tag.get("supplier_addon_id")) != self.addon_id:
            return None
        manual_slug = tag.get("manual_supplier_slug") or tag.get("supplier_ref")
        manual_slug = str(manual_slug) if manual_slug else None
        if not manual_slug:
            return None
        product_id = tag.get("supplier_product_id")
        product_id = str(product_id) if product_id else ""
        variant_id = tag.get("supplier_variant_id")
        variant_id = str(variant_id) if variant_id else None
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
        if not supplier_value.startswith("manual:"):
            return None
        slug = supplier_value.removeprefix("manual:")
        if not slug:
            return None
        tag: dict[str, str] = {
            "supplier_addon_id": self.addon_id,
            "manual_supplier_slug": slug,
        }
        if supplier_product_id.strip():
            tag["supplier_product_id"] = supplier_product_id.strip()
        return tag

    def validate_admin_form(
        self,
        supplier_value: str,
        supplier_product_id: str = "",
        supplier_variant_id: str = "",
    ) -> str | None:
        if not supplier_value.startswith("manual:"):
            return "Invalid manual supplier selection."
        slug = supplier_value.removeprefix("manual:")
        if not slug:
            return "Manual supplier slug is required."
        return None

    def fulfillment_key(self, assignment: SupplierAssignment) -> str:
        if assignment.manual_slug:
            return f"manual:{assignment.manual_slug}"
        return self.addon_id

    def assignment_dropdown_value(self, assignment: SupplierAssignment) -> str:
        if assignment.manual_slug:
            return f"manual:{assignment.manual_slug}"
        return self.addon_id

    def assignment_display_label(self, assignment: SupplierAssignment) -> str:
        if assignment.manual_slug:
            return f"Manual: {assignment.manual_slug}"
        return self.addon_name

    def lists_options_when_disabled(self) -> bool:
        return True

    async def list_admin_options(self, session: Any) -> list[SupplierOption]:
        if session is None:
            return []
        from app.services.manual_suppliers import list_manual_suppliers

        rows = await list_manual_suppliers(session, active_only=True)
        return [
            SupplierOption(
                value=f"manual:{row.slug}",
                label=f"Manual: {row.name}",
                addon_id=self.addon_id,
                manual_slug=row.slug,
            )
            for row in rows
        ]

    async def list_products(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """List active manual supplier definitions."""
        from app.db.connection import session_scope
        from app.services.manual_suppliers import list_manual_suppliers

        async with session_scope() as session:
            rows = await list_manual_suppliers(session, active_only=True)
        return [
            {
                "id": row.slug,
                "name": row.name,
                "contact_email": row.contact_email,
                "contact_phone": row.contact_phone,
                "notes": row.notes,
            }
            for row in rows
        ]

    async def get_product(self, product_id: str) -> Dict[str, Any]:
        from app.db.connection import session_scope
        from app.services.manual_suppliers import get_manual_supplier

        async with session_scope() as session:
            row = await get_manual_supplier(session, product_id)
        if row is None:
            return {"error": f"Manual supplier '{product_id}' not found"}
        return {
            "id": row.slug,
            "name": row.name,
            "contact_email": row.contact_email,
            "contact_phone": row.contact_phone,
            "notes": row.notes,
            "is_active": row.is_active,
        }

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
        del shipping_method, currency
        if not supplier_ref:
            return {"success": False, "error": "manual_supplier_slug is required"}

        from app.db.connection import session_scope
        from app.services.manual_suppliers import get_manual_supplier

        async with session_scope() as session:
            supplier = await get_manual_supplier(session, supplier_ref)

        if supplier is None:
            return {
                "success": False,
                "error": f"Manual supplier '{supplier_ref}' not found",
            }
        if not supplier.is_active:
            return {
                "success": False,
                "error": f"Manual supplier '{supplier_ref}' is inactive",
            }

        payload = {
            "success": True,
            "type": "manual",
            "supplier_slug": supplier.slug,
            "supplier_name": supplier.name,
            "contact_email": supplier.contact_email,
            "contact_phone": supplier.contact_phone,
            "supplier_notes": supplier.notes,
            "external_id": external_id,
            "items": items,
            "shipping_address": shipping_address,
            "status": "pending_manual_fulfillment",
        }
        info("Manual", "Fulfillment task for order {} → {} ({} items)",
            external_id,
            supplier.slug,
            len(items),
        )
        return payload

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "status": "manual",
            "detail": "Manual suppliers do not expose external order tracking",
        }

    async def sync_inventory(self) -> None:
        info("Manual", "sync_inventory is a no-op for manual suppliers")

    def get_routers(self) -> List[APIRouter]:
        from app.addons.suppliers.manual.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.suppliers.manual.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "templates")

    def get_admin_static(self) -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parent / "static")
