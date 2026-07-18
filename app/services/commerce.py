"""Commerce helpers: inventory, cart loading, order status side effects.

Inventory updates use raw SQL (``sqlalchemy.text`` or ``execute_raw`` on D1 sessions)
for atomic ``UPDATE … WHERE inventory_quantity >= ?`` semantics. After a successful
raw update, call ``session.refresh(product)`` so the ORM identity map reflects the new
``inventory_quantity`` — otherwise in-process reads may return stale stock levels.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy import text
from sqlmodel import col, select

from app.core.exceptions import ValidationError
from models.cart import Cart
from models.cart_item import CartItem
from models.order import Order
from models.order_item import OrderItem
from models.product import Product
from models.product_variant import ProductVariant
from app.services.product_variants import (
    build_variant_snapshot,
    refresh_product_listing_cache,
)

logger = logging.getLogger(__name__)

_INVENTORY_RESTORABLE = frozenset({"pending", "paid"})

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "cancelled"}),
    "paid": frozenset({"shipped", "cancelled"}),
    # shipped -> cancelled is intentionally absent: inventory is not restorable
    # after shipment; returns need a dedicated restock workflow.
    "shipped": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}


def allowed_next_statuses(current_status: str) -> frozenset[str]:
    """Return valid target statuses from the current order status."""
    return VALID_TRANSITIONS.get(current_status, frozenset())


def validate_status_transition(old_status: str, new_status: str) -> None:
    """Raise if transitioning from old_status to new_status is not allowed."""
    if new_status not in allowed_next_statuses(old_status):
        raise ValidationError(
            message=f"Cannot transition order from '{old_status}' to '{new_status}'"
        )


def cart_line_totals(
    cart_items: list[Any],
    products: dict[int, Product],
    variants: dict[int, ProductVariant],
) -> tuple[int, list[dict[str, Any]]]:
    """Return (subtotal_cents, order_items_data) for cart line items."""
    order_items_data = build_cart_pricing_lines(
        cart_items,
        products,
        variants,
        include_variant_snapshot=True,
    )
    subtotal_cents = sum(item["total_price_cents"] for item in order_items_data)
    return subtotal_cents, order_items_data


def build_cart_pricing_lines(
    cart_items: list[Any],
    products: dict[int, Product],
    variants: dict[int, ProductVariant],
    *,
    include_variant_snapshot: bool = False,
) -> list[dict[str, Any]]:
    """Build canonical cart/order pricing lines from product + variant maps."""
    lines: list[dict[str, Any]] = []
    for item in cart_items:
        product_id = getattr(item, "product_id", None)
        variant_id = getattr(item, "variant_id", None)
        product = products.get(product_id)
        variant = variants.get(variant_id)
        if product is None or variant is None:
            raise ValidationError(
                message=(
                    "Cart contains a missing product or variant and cannot be priced. "
                    f"(product_id={product_id}, variant_id={variant_id})"
                )
            )
        quantity = getattr(item, "quantity", 1)
        line_total = variant.price_cents * quantity
        line = {
            "product_id": product.id,
            "variant_id": variant.id,
            "product_name": product.name,
            "product_sku": variant.sku or f"SKU-{variant.id}",
            "quantity": quantity,
            "unit_price_cents": variant.price_cents,
            "total_price_cents": line_total,
        }
        if include_variant_snapshot:
            line["variant_snapshot"] = build_variant_snapshot(variant)
        lines.append(line)
    return lines


def ensure_product_purchasable(product: Product) -> None:
    """Raise if a product cannot be added to cart or checked out."""
    if product.status != "published":
        raise ValidationError(
            message=f"Product '{product.name}' is not available for purchase"
        )


async def load_variants_for_cart_items(
    session: Any, items: Sequence[Any]
) -> dict[int, ProductVariant]:
    """Batch-load variants for cart/order line items (one IN query, no N+1)."""
    ids = {item.variant_id for item in items if item.variant_id is not None}
    if not ids:
        return {}
    result = await session.execute(
        select(ProductVariant).where(col(ProductVariant.id).in_(ids))
    )
    return {variant.id: variant for variant in result.scalars().all()}


async def load_cart_items(session: Any, cart_id: int) -> list[CartItem]:
    """Load cart line items explicitly (works on D1 and SQLite)."""
    result = await session.execute(
        select(CartItem).where(col(CartItem.cart_id) == cart_id)
    )
    return list(result.scalars().all())


async def load_products_for_cart_items(
    session: Any, items: Sequence[Any]
) -> dict[int, Product]:
    """Batch-load products for cart/order line items (one IN query, no N+1)."""
    ids = {item.product_id for item in items if item.product_id is not None}
    if not ids:
        return {}
    result = await session.execute(select(Product).where(col(Product.id).in_(ids)))
    return {product.id: product for product in result.scalars().all()}


async def load_user_cart(session: Any, user_id: int) -> tuple[Cart | None, list[CartItem]]:
    """Load a user's cart and line items without ORM lazy loads."""
    result = await session.execute(select(Cart).where(col(Cart.user_id) == user_id))
    cart = result.scalar_one_or_none()
    if cart is None:
        return None, []
    items = await load_cart_items(session, cart.id)
    return cart, items


async def load_order_items(session: Any, order_id: int) -> list[OrderItem]:
    result = await session.execute(
        select(OrderItem).where(col(OrderItem.order_id) == order_id)
    )
    return list(result.scalars().all())


async def _refresh_product_cache_for_variant(session: Any, variant_id: int) -> None:
    variant = await session.get(ProductVariant, variant_id)
    if variant is None:
        return
    product = await session.get(Product, variant.product_id)
    if product is None:
        return
    rows = await session.execute(
        select(ProductVariant).where(col(ProductVariant.product_id) == product.id)
    )
    refresh_product_listing_cache(product, list(rows.scalars().all()))


async def atomic_decrement_variant_inventory(
    session: Any, variant_id: int, quantity: int
) -> None:
    """Atomically reduce variant inventory; raises if insufficient stock."""
    if quantity <= 0:
        return

    if hasattr(session, "execute_raw"):
        changes = await session.execute_raw(
            "UPDATE product_variants SET inventory_quantity = inventory_quantity - ? "
            "WHERE id = ? AND inventory_quantity >= ?",
            [quantity, variant_id, quantity],
        )
        if changes == 0:
            variant = await session.get(ProductVariant, variant_id)
            title = variant.title if variant else str(variant_id)
            raise ValidationError(message=f"Insufficient inventory for variant '{title}'")
        await _refresh_product_cache_for_variant(session, variant_id)
        return

    result = await session.execute(
        text(
            "UPDATE product_variants SET inventory_quantity = inventory_quantity - :qty "
            "WHERE id = :id AND inventory_quantity >= :qty"
        ),
        {"qty": quantity, "id": variant_id},
    )
    if result.rowcount == 0:
        variant = await session.get(ProductVariant, variant_id)
        title = variant.title if variant else str(variant_id)
        raise ValidationError(message=f"Insufficient inventory for variant '{title}'")
    await _refresh_product_cache_for_variant(session, variant_id)


async def restore_variant_inventory(session: Any, variant_id: int, quantity: int) -> None:
    """Return reserved variant inventory when an order is cancelled."""
    if quantity <= 0:
        return

    if hasattr(session, "execute_raw"):
        await session.execute_raw(
            "UPDATE product_variants SET inventory_quantity = inventory_quantity + ? WHERE id = ?",
            [quantity, variant_id],
        )
        await _refresh_product_cache_for_variant(session, variant_id)
        return

    await session.execute(
        text(
            "UPDATE product_variants SET inventory_quantity = inventory_quantity + :qty "
            "WHERE id = :id"
        ),
        {"qty": quantity, "id": variant_id},
    )
    await _refresh_product_cache_for_variant(session, variant_id)


async def reserve_order_inventory(session: Any, items: Sequence[OrderItem]) -> None:
    """Atomically decrement inventory for each order line."""
    decremented: list[tuple[int, int]] = []
    try:
        for item in items:
            if item.variant_id is None:
                raise ValidationError(message="Order item missing variant_id")
            await atomic_decrement_variant_inventory(session, item.variant_id, item.quantity)
            decremented.append((item.variant_id, item.quantity))
    except Exception:
        for variant_id, quantity in reversed(decremented):
            await restore_variant_inventory(session, variant_id, quantity)
        raise


async def release_order_inventory(session: Any, items: Sequence[OrderItem]) -> None:
    """Restore inventory for each order line."""
    for item in items:
        if item.variant_id is not None:
            await restore_variant_inventory(session, item.variant_id, item.quantity)


def apply_order_tracking(
    order: Order,
    *,
    tracking_number: str | None = None,
    tracking_url: str | None = None,
    carrier: str | None = None,
) -> None:
    """Persist shipment tracking fields on an order."""
    if tracking_number is not None:
        order.tracking_number = tracking_number.strip() or None
    if tracking_url is not None:
        order.tracking_url = tracking_url.strip() or None
    if carrier is not None:
        order.carrier = carrier.strip() or None


async def apply_order_status_change(
    session: Any, order: Order, new_status: str
) -> None:
    """Apply inventory side effects when an order status changes."""
    old_status = order.status
    if old_status == new_status:
        return

    if new_status not in allowed_next_statuses(old_status):
        raise ValidationError(
            message=f"Cannot transition order from '{old_status}' to '{new_status}'"
        )

    items = await load_order_items(session, order.id)

    if new_status == "cancelled" and old_status in _INVENTORY_RESTORABLE:
        await release_order_inventory(session, items)
        if old_status == "paid":
            from app.services.product_popularity import decrement_product_units_sold

            await decrement_product_units_sold(session, items)
    elif new_status == "paid" and old_status == "pending":
        from app.services.product_popularity import increment_product_units_sold

        await increment_product_units_sold(session, items)

    order.status = new_status
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)

    if new_status == "paid" and old_status == "pending":
        # Payment is the source of truth: fulfillment runs after the paid state
        # is set and must never abort it. Failures are recorded on the order
        # (notes + supplier_orders) for retry/manual follow-up.
        from app.services.fulfillment import fulfill_order_with_suppliers

        try:
            await fulfill_order_with_suppliers(session, order, items)
        except Exception:
            logger.exception("Fulfillment failed for paid order %s", order.id)

    from app.services.notifications import notify_order_status_change

    await notify_order_status_change(session, order, old_status, new_status)


async def cancel_order_as_admin(session: Any, order: Order) -> None:
    """Cancel an order with admin-specific guardrails for paid and shipped states."""
    if order.status == "cancelled":
        return
    if order.status == "pending":
        await apply_order_status_change(session, order, "cancelled")
        return
    if order.status == "paid":
        from app.services.payments import mark_refund_required_for_cancelled_order

        await apply_order_status_change(session, order, "cancelled")
        mark_refund_required_for_cancelled_order(session, order)
        return
    if order.status in {"shipped", "delivered"}:
        raise ValidationError(
            message=(
                "Cannot cancel shipped or delivered orders from the admin status flow. "
                "Use a separate return/restock workflow."
            )
        )
    raise ValidationError(
        message=f"Cannot cancel order from status '{order.status}'"
    )


def _order_read(order: Order, items: list[OrderItem]):
    from schemas.order import OrderItemRead, OrderRead

    read = OrderRead.model_validate(order)
    return read.model_copy(
        update={
            "subtotal_cents": sum(item.total_price_cents for item in items),
            "items": [OrderItemRead.model_validate(item) for item in items],
        }
    )


async def serialize_order(session: Any, order: Order):
    """Build an OrderRead schema without triggering ORM lazy loads."""
    return _order_read(order, await load_order_items(session, order.id))


async def serialize_orders(session: Any, orders: Sequence[Order]) -> list:
    """Serialize many orders with one batched item query instead of one per order."""
    if not orders:
        return []
    result = await session.execute(
        select(OrderItem).where(col(OrderItem.order_id).in_([o.id for o in orders]))
    )
    by_order: dict[int, list[OrderItem]] = {}
    for item in result.scalars().all():
        by_order.setdefault(item.order_id, []).append(item)
    return [_order_read(order, by_order.get(order.id, [])) for order in orders]
