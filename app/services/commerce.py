"""Commerce helpers: inventory, cart loading, order status side effects.

Inventory updates use raw SQL (``sqlalchemy.text`` or ``execute_raw`` on D1 sessions)
for atomic ``UPDATE … WHERE inventory_quantity >= ?`` semantics. After a successful
raw update, call ``session.refresh(product)`` so the ORM identity map reflects the new
``inventory_quantity`` — otherwise in-process reads may return stale stock levels.
"""

from __future__ import annotations

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
    ensure_variant_purchasable,
    refresh_product_listing_cache,
)

_INVENTORY_RESERVED = frozenset({"pending", "paid", "shipped", "delivered"})

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "cancelled"}),
    "paid": frozenset({"shipped", "cancelled"}),
    "shipped": frozenset({"delivered", "cancelled"}),
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
    subtotal_cents = 0
    order_items_data: list[dict[str, Any]] = []
    for item in cart_items:
        product = products.get(getattr(item, "product_id", None))
        variant = variants.get(getattr(item, "variant_id", None))
        if product is None or variant is None:
            continue
        quantity = getattr(item, "quantity", 1)
        line_total = variant.price_cents * quantity
        subtotal_cents += line_total
        order_items_data.append(
            {
                "product_id": product.id,
                "variant_id": variant.id,
                "product_name": product.name,
                "product_sku": variant.sku or f"SKU-{variant.id}",
                "quantity": quantity,
                "unit_price_cents": variant.price_cents,
                "total_price_cents": line_total,
                "variant_snapshot": build_variant_snapshot(variant),
            }
        )
    return subtotal_cents, order_items_data


def ensure_product_purchasable(product: Product) -> None:
    """Raise if a product cannot be added to cart or checked out."""
    if product.status != "published":
        raise ValidationError(
            message=f"Product '{product.name}' is not available for purchase"
        )


def ensure_product_in_stock(product: Product, variant: ProductVariant, quantity: int = 1) -> None:
    """Raise if published product variant does not have enough inventory."""
    ensure_variant_purchasable(product, variant, quantity)


async def load_variants_for_cart_items(
    session: Any, items: Sequence[CartItem]
) -> dict[int, ProductVariant]:
    """Load variants for cart line items."""
    variants: dict[int, ProductVariant] = {}
    for item in items:
        if item.variant_id in variants:
            continue
        variant = await session.get(ProductVariant, item.variant_id)
        if variant is not None:
            variants[item.variant_id] = variant
    return variants


async def load_cart_items(session: Any, cart_id: int) -> list[CartItem]:
    """Load cart line items explicitly (works on D1 and SQLite)."""
    result = await session.execute(
        select(CartItem).where(col(CartItem.cart_id) == cart_id)
    )
    return list(result.scalars().all())


async def load_products_for_cart_items(
    session: Any, items: Sequence[CartItem]
) -> dict[int, Product]:
    """Load products for cart line items without ORM lazy loads."""
    products: dict[int, Product] = {}
    for item in items:
        if item.product_id in products:
            continue
        product = await session.get(Product, item.product_id)
        if product is not None:
            products[item.product_id] = product
    return products


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

    if new_status == "cancelled" and old_status in _INVENTORY_RESERVED:
        await release_order_inventory(session, items)
        if old_status == "paid":
            from app.services.product_popularity import decrement_product_units_sold

            await decrement_product_units_sold(session, items)
    elif new_status == "paid" and old_status == "pending":
        from app.services.fulfillment import fulfill_order_with_suppliers
        from app.services.product_popularity import increment_product_units_sold

        await fulfill_order_with_suppliers(session, order, items)
        await increment_product_units_sold(session, items)

    order.status = new_status
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)

    from app.services.notifications import notify_order_status_change

    await notify_order_status_change(session, order, old_status, new_status)


async def serialize_order(session: Any, order: Order):
    """Build an OrderRead schema without triggering ORM lazy loads."""
    from schemas.order import OrderItemRead, OrderRead

    items = await load_order_items(session, order.id)
    subtotal_cents = sum(item.total_price_cents for item in items)
    read = OrderRead.model_validate(order)
    return read.model_copy(
        update={
            "subtotal_cents": subtotal_cents,
            "items": [OrderItemRead.model_validate(item) for item in items],
        }
    )
