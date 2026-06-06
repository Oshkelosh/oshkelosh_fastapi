"""Supplier fulfillment side effects via supplier addons."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from app.services.addons import get_supplier_addon
from models.product import Product

logger = logging.getLogger(__name__)


def _supplier_tag(product: Product) -> tuple[str, str] | None:
    """Return (supplier_addon_id, supplier_product_id) from product tags if set."""
    for tag in product.tags or []:
        if not isinstance(tag, dict):
            continue
        supplier_id = tag.get("supplier_addon_id")
        product_id = tag.get("supplier_product_id")
        if supplier_id and product_id:
            return str(supplier_id), str(product_id)
    return None


async def fulfill_order_with_suppliers(session: Any, order: Any, items: list) -> None:
    """Create supplier fulfillment orders for tagged line items."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        product = await session.get(Product, item.product_id)
        if product is None:
            continue
        tag = _supplier_tag(product)
        if tag is None:
            continue
        supplier_id, supplier_product_id = tag
        grouped[supplier_id].append(supplier_product_id)

    if not grouped:
        return

    shipping_address = order.shipping_address or {}
    notes_parts: list[str] = []

    for supplier_id, product_ids in grouped.items():
        addon = get_supplier_addon(supplier_id)
        if addon is None:
            logger.warning(
                "Supplier addon '%s' not enabled; skipping fulfillment for order %s",
                supplier_id,
                order.id,
            )
            continue
        try:
            result = await addon.create_order(product_ids, shipping_address)
            notes_parts.append(
                json.dumps({"supplier": supplier_id, "result": result}, default=str)
            )
            if not result.get("success", True):
                logger.warning(
                    "Supplier %s fulfillment failed for order %s: %s",
                    supplier_id,
                    order.id,
                    result.get("error", result),
                )
        except Exception:
            logger.exception(
                "Supplier %s fulfillment error for order %s",
                supplier_id,
                order.id,
            )

    if notes_parts:
        existing = order.notes or ""
        fulfillment_note = "\n".join(notes_parts)
        order.notes = f"{existing}\n{fulfillment_note}".strip() if existing else fulfillment_note
        if hasattr(session, "mark_dirty"):
            session.mark_dirty(order)
