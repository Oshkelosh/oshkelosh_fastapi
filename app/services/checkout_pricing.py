"""Checkout tax and shipping orchestration (Site Settings + addon seams).

Tax amounts use integer cents with truncating division (``int(value * rate / 10000)``),
matching common payment-processor rounding. Amounts are never rounded up implicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.pricing.protocols import TaxQuote
from app.services.commerce import cart_line_totals
from app.services.pricing.shipping import SiteShippingQuoter
from app.services.pricing.site import SiteTaxQuoter
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
    lines: list[dict[str, Any]] = []
    for item in cart_items:
        product = products.get(item.product_id)
        variant = variants.get(getattr(item, "variant_id", None))
        if product is None or variant is None:
            continue
        quantity = getattr(item, "quantity", 1)
        lines.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "quantity": quantity,
                "unit_price_cents": variant.price_cents,
                "total_price_cents": variant.price_cents * quantity,
            }
        )
    return lines


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
        site_quote = await SiteTaxQuoter(site).quote(
            tax_line_items,
            shipping_address,
            subtotal_cents,
        )
        if site_quote is not None:
            tax_cents = max(0, int(site_quote.tax_cents))
            tax_source = site_quote.source
        else:
            tax_cents = 0
            tax_source = "disabled"

    shipping_quote = await SiteShippingQuoter(site).quote(
        cart_items,
        products,
        shipping_address,
        variants,
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
    from app.services.commerce import load_order_items

    items = await load_order_items(session, order.id)
    products: dict[int, Product] = {}
    variants: dict[int, ProductVariant] = {}
    for item in items:
        if item.product_id not in products:
            product = await session.get(Product, item.product_id)
            if product is not None:
                products[item.product_id] = product
        if item.variant_id is not None and item.variant_id not in variants:
            variant = await session.get(ProductVariant, item.variant_id)
            if variant is not None:
                variants[item.variant_id] = variant

    charges = await quote_order_charges(
        items,
        products,
        order.shipping_address,
        site,
        variants,
    )
    subtotal_cents = sum(item.total_price_cents for item in items)
    order.tax_cents = charges.tax_cents
    order.shipping_cents = charges.shipping_cents
    order.total_cents = compute_order_total_cents(subtotal_cents, charges, site)
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)
