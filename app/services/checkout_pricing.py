"""Checkout tax and shipping orchestration (Site Settings + addon seams).

Tax amounts use integer cents with truncating division (``int(value * rate / 10000)``),
matching common payment-processor rounding. Amounts are never rounded up implicitly.
"""

from __future__ import annotations

from copy import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.currency import shop_currency_from_settings
from app.services.pricing.protocols import TaxQuote
from app.services.commerce import build_cart_pricing_lines, cart_line_totals
from app.services.pricing.shipping import SiteShippingQuoter
from app.services.pricing.tax_rules import compute_site_shipping_cents, compute_site_tax_cents
from app.services.tax_discovery import get_tax_tool
from models.product import Product
from models.product_variant import ProductVariant
from models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

__all__ = [
    "OrderCharges",
    "_cart_subtotal_cents",
    "compute_order_total_cents",
    "compute_site_shipping_cents",
    "compute_site_tax_cents",
    "quote_order_charges",
    "reprice_pending_order",
    "try_tax_tool_quote",
]


@dataclass
class OrderCharges:
    """Resolved tax and shipping for an order."""

    tax_cents: int
    shipping_cents: int
    tax_source: str
    shipping_breakdown: list[dict[str, Any]] = field(default_factory=list)


def _build_tax_line_items(
    cart_items: list[Any],
    products: dict[int, Product],
    variants: dict[int, ProductVariant],
) -> list[dict[str, Any]]:
    return [
        {
            "product_id": line["product_id"],
            "product_name": line["product_name"],
            "quantity": line["quantity"],
            "unit_price_cents": line["unit_price_cents"],
            "total_price_cents": line["total_price_cents"],
        }
        for line in build_cart_pricing_lines(cart_items, products, variants)
    ]


def _cart_subtotal_cents(
    cart_items: list[Any],
    products: dict[int, Product],
    variants: dict[int, ProductVariant],
) -> int:
    subtotal_cents, _ = cart_line_totals(cart_items, products, variants)
    return subtotal_cents


async def try_tax_tool_quote(
    tax_tool: Any,
    line_items: list[dict[str, Any]],
    shipping_address: dict[str, Any] | None,
    subtotal_cents: int,
) -> TaxQuote | None:
    """Attempt tax quote from an enabled tax-tool addon; None on failure or no quote."""
    if subtotal_cents <= 0:
        return None
    try:
        return await tax_tool.quote_tax(line_items, shipping_address, subtotal_cents)
    except Exception as exc:
        logger.warning(
            "Tax tool '%s' quote_tax failed; using site settings: %s",
            tax_tool.addon_id,
            exc,
        )
        return None


async def quote_order_charges(
    cart_items: list[Any],
    products: dict[int, Product],
    shipping_address: dict[str, Any] | None,
    site: SiteSettings,
    variants: dict[int, ProductVariant],
    shipping_selections: dict[str, str] | None = None,
    currency: str | None = None,
) -> OrderCharges:
    """Resolve tax and shipping for a cart at checkout."""
    subtotal_cents = _cart_subtotal_cents(cart_items, products, variants)

    tax_line_items = _build_tax_line_items(cart_items, products, variants)
    tax_cents = 0
    tax_source = "disabled"

    tax_tool = get_tax_tool()
    tool_quote: TaxQuote | None = None
    if tax_tool is not None:
        tool_quote = await try_tax_tool_quote(
            tax_tool,
            tax_line_items,
            shipping_address,
            subtotal_cents,
        )

    if tool_quote is not None:
        tax_cents = max(0, int(tool_quote.tax_cents))
        tax_source = tool_quote.source or "tax_tool"
        if tax_source == "site_settings":
            tax_source = "tax_tool"
    else:
        site_tax_cents, site_source = compute_site_tax_cents(
            subtotal_cents,
            site,
            shipping_address,
        )
        if site_source != "disabled":
            tax_cents = max(0, int(site_tax_cents))
            tax_source = site_source

    shop_currency = currency or shop_currency_from_settings(site)
    shipping_quote = await SiteShippingQuoter(site).quote(
        cart_items,
        products,
        shipping_address,
        variants,
        shipping_selections=shipping_selections,
        currency=shop_currency,
    )

    return OrderCharges(
        tax_cents=tax_cents,
        shipping_cents=shipping_quote.shipping_cents,
        tax_source=tax_source,
        shipping_breakdown=shipping_quote.breakdown,
    )


def compute_order_total_cents(
    subtotal_cents: int,
    charges: OrderCharges,
    site: SiteSettings,
) -> int:
    """Compute order total from merchandise subtotal and quoted charges.

    When ``site.tax_inclusive`` is true, tax is embedded in subtotal — do not add
  ``charges.tax_cents`` again. Otherwise tax is additive on top of subtotal.
    """
    if site.tax_inclusive:
        return subtotal_cents + charges.shipping_cents
    return subtotal_cents + charges.tax_cents + charges.shipping_cents


async def reprice_pending_order(session: Any, order: Any, site: SiteSettings) -> None:
    """Re-quote tax/shipping and update totals on a pending order."""
    from app.services.commerce import (
        load_order_items,
        load_products_for_cart_items,
        load_variants_for_cart_items,
    )
    from app.services.currency import normalize_currency

    items = await load_order_items(session, order.id)
    products = await load_products_for_cart_items(session, items)
    variants = await load_variants_for_cart_items(session, items)

    priced_variants = {
        variant_id: copy(variant)
        for variant_id, variant in variants.items()
    }
    for item in items:
        if item.variant_id is None:
            continue
        priced_variant = priced_variants.get(item.variant_id)
        if priced_variant is not None:
            priced_variant.price_cents = item.unit_price_cents

    charges = await quote_order_charges(
        items,
        products,
        order.shipping_address,
        site,
        priced_variants,
        shipping_selections=getattr(order, "shipping_selections", None),
        currency=normalize_currency(
            getattr(order, "currency", None),
            default=shop_currency_from_settings(site),
        ),
    )
    subtotal_cents = sum(item.total_price_cents for item in items)
    order.tax_cents = charges.tax_cents
    order.shipping_cents = charges.shipping_cents
    order.total_cents = compute_order_total_cents(subtotal_cents, charges, site)
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)
