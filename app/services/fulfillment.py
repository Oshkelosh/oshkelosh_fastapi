"""Supplier fulfillment side effects via supplier addons."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.services.addons import get_supplier_addon
from app.services.suppliers import SupplierAssignment
from models.product import Product
from models.product_variant import ProductVariant

logger = logging.getLogger(__name__)


@dataclass
class FulfillmentGroup:
    """Line items routed to one supplier destination."""

    assignment: SupplierAssignment
    items: list[dict[str, Any]] = field(default_factory=list)


def _supplier_line_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "supplier_product_id": item["supplier_product_id"],
            "supplier_variant_id": item.get("supplier_variant_id"),
            "quantity": item["quantity"],
            "product_name": item.get("product_name", ""),
        }
        for item in items
    ]


def _append_note(session: Any, order: Any, note: str) -> None:
    existing = order.notes or ""
    order.notes = f"{existing}\n{note}".strip() if existing else note
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)


def _supplier_order_id(result: dict[str, Any]) -> str | None:
    for key in ("order_id", "supplier_order_id", "id"):
        value = result.get(key)
        if value:
            return str(value)
    return None


async def fulfill_order_with_suppliers(session: Any, order: Any, items: list) -> list[str]:
    """Create supplier fulfillment orders for tagged line items.

    Results are persisted on ``order.supplier_orders`` keyed by shipping group,
    so a re-run (retry after partial failure) skips groups that already have a
    successful supplier order instead of ordering twice. Failures are recorded
    on the order and returned; they must not abort the caller's transaction —
    payment has already happened.
    """
    from app.services.pricing.shipping import group_cart_for_shipping

    products: dict[int, Product] = {}
    variants: dict[int, ProductVariant] = {}
    for item in items:
        product = await session.get(Product, item.product_id)
        if product is not None:
            products[item.product_id] = product
        if item.variant_id is not None:
            variant = await session.get(ProductVariant, item.variant_id)
            if variant is not None:
                variants[item.variant_id] = variant

    shipping_groups = group_cart_for_shipping(items, products, variants)
    grouped: dict[str, FulfillmentGroup] = {}
    for group in shipping_groups:
        if group.assignment is None:
            continue
        key = group.key
        grouped[key] = FulfillmentGroup(
            assignment=group.assignment,
            items=group.items,
        )

    if not grouped:
        return []

    shipping_address = order.shipping_address or {}
    selections = getattr(order, "shipping_selections", None) or {}
    external_id = str(getattr(order, "id", "")) or None
    failures: list[str] = []
    supplier_orders: dict[str, Any] = dict(getattr(order, "supplier_orders", None) or {})

    for key, group in grouped.items():
        previous = supplier_orders.get(key)
        if isinstance(previous, dict) and previous.get("success"):
            logger.info(
                "Skipping already fulfilled group %s for order %s (supplier order %s)",
                key,
                order.id,
                previous.get("supplier_order_id"),
            )
            continue

        assignment = group.assignment
        addon = get_supplier_addon(assignment.addon_id)
        if addon is None:
            logger.warning(
                "Supplier addon '%s' not enabled; skipping fulfillment for order %s",
                assignment.addon_id,
                order.id,
            )
            failure_note = f"Supplier addon '{assignment.addon_id}' is not enabled"
            _append_note(session, order, failure_note)
            failures.append(failure_note)
            supplier_orders[key] = {
                "addon_id": assignment.addon_id,
                "success": False,
                "error": failure_note,
            }
            continue
        try:
            method = selections.get(key) or selections.get(assignment.addon_id)
            result = await addon.create_order(
                _supplier_line_items(group.items),
                shipping_address,
                external_id=external_id,
                supplier_ref=assignment.manual_slug,
                shipping_method=str(method) if method else None,
                currency=str(order.currency).upper() if order.currency else None,
            )
            supplier_orders[key] = {
                "addon_id": assignment.addon_id,
                "success": bool(result.get("success", False)),
                "supplier_order_id": _supplier_order_id(result),
                "error": result.get("error"),
            }
            _append_note(
                session,
                order,
                json.dumps(
                    {"supplier": key, "addon_id": assignment.addon_id, "result": result},
                    default=str,
                ),
            )
            if not result.get("success", False):
                logger.warning(
                    "Supplier %s fulfillment failed for order %s: %s",
                    key,
                    order.id,
                    result.get("error", result),
                )
                failure_note = f"Fulfillment failed for {key}: {result.get('error', result)}"
                _append_note(session, order, failure_note)
                failures.append(failure_note)
            config_updates = result.get("config_updates")
            if isinstance(config_updates, dict) and config_updates:
                from app.services.addons import merge_config_updates, persist_addon_config

                merged = merge_config_updates(assignment.addon_id, config_updates)
                await persist_addon_config(session, assignment.addon_id, merged, addon.is_enabled)
        except Exception as exc:
            logger.exception(
                "Supplier %s fulfillment error for order %s",
                key,
                order.id,
            )
            failure_note = f"Fulfillment error for {key}: {exc}"
            _append_note(session, order, failure_note)
            failures.append(failure_note)
            supplier_orders[key] = {
                "addon_id": assignment.addon_id,
                "success": False,
                "error": str(exc),
            }

    order.supplier_orders = supplier_orders
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)

    return failures
