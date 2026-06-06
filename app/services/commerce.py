"""Commerce helpers: inventory, cart loading, order status side effects."""

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

DEFAULT_TAX_RATE = 0.08
DEFAULT_SHIPPING_CENTS = 500

_INVENTORY_COMMITTED = frozenset({"paid", "shipped", "delivered"})


def ensure_product_purchasable(product: Product) -> None:
    """Raise if a product cannot be added to cart or checked out."""
    if product.status != "published":
        raise ValidationError(
            message=f"Product '{product.name}' is not available for purchase"
        )


async def load_cart_items(session: Any, cart_id: int) -> list[CartItem]:
    """Load cart line items explicitly (works on D1 and SQLite)."""
    result = await session.execute(
        select(CartItem).where(col(CartItem.cart_id) == cart_id)
    )
    return list(result.scalars().all())


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


async def atomic_decrement_inventory(
    session: Any, product_id: int, quantity: int
) -> None:
    """Atomically reduce inventory; raises if insufficient stock."""
    if quantity <= 0:
        return

    if hasattr(session, "execute_raw"):
        changes = await session.execute_raw(
            "UPDATE products SET inventory_quantity = inventory_quantity - ? "
            "WHERE id = ? AND inventory_quantity >= ?",
            [quantity, product_id, quantity],
        )
        if changes == 0:
            product = await session.get(Product, product_id)
            name = product.name if product else str(product_id)
            raise ValidationError(message=f"Insufficient inventory for product '{name}'")
        return

    result = await session.execute(
        text(
            "UPDATE products SET inventory_quantity = inventory_quantity - :qty "
            "WHERE id = :id AND inventory_quantity >= :qty"
        ),
        {"qty": quantity, "id": product_id},
    )
    if result.rowcount == 0:
        product = await session.get(Product, product_id)
        name = product.name if product else str(product_id)
        raise ValidationError(message=f"Insufficient inventory for product '{name}'")


async def restore_inventory(session: Any, product_id: int, quantity: int) -> None:
    """Return reserved inventory when an order is cancelled."""
    if quantity <= 0:
        return

    if hasattr(session, "execute_raw"):
        await session.execute_raw(
            "UPDATE products SET inventory_quantity = inventory_quantity + ? WHERE id = ?",
            [quantity, product_id],
        )
        return

    await session.execute(
        text(
            "UPDATE products SET inventory_quantity = inventory_quantity + :qty "
            "WHERE id = :id"
        ),
        {"qty": quantity, "id": product_id},
    )


def compute_order_charges(subtotal_cents: int) -> tuple[int, int]:
    """Return (tax_cents, shipping_cents) from subtotal."""
    tax_cents = int(subtotal_cents * DEFAULT_TAX_RATE)
    return tax_cents, DEFAULT_SHIPPING_CENTS


async def reserve_order_inventory(session: Any, items: Sequence[OrderItem]) -> None:
    """Decrement inventory for each order line when payment is confirmed."""
    for item in items:
        await atomic_decrement_inventory(session, item.product_id, item.quantity)


async def release_order_inventory(session: Any, items: Sequence[OrderItem]) -> None:
    """Restore inventory for each order line."""
    for item in items:
        await restore_inventory(session, item.product_id, item.quantity)


async def apply_order_status_change(
    session: Any, order: Order, new_status: str
) -> None:
    """Apply inventory side effects when an order status changes."""
    old_status = order.status
    if old_status == new_status:
        return

    items = await load_order_items(session, order.id)

    if new_status == "cancelled" and old_status in _INVENTORY_COMMITTED:
        await release_order_inventory(session, items)
    elif new_status == "paid" and old_status == "pending":
        await reserve_order_inventory(session, items)
        from app.services.fulfillment import fulfill_order_with_suppliers

        await fulfill_order_with_suppliers(session, order, items)

    order.status = new_status
    if hasattr(session, "mark_dirty"):
        session.mark_dirty(order)

    from app.services.notifications import notify_order_status_change

    await notify_order_status_change(session, order, old_status, new_status)


async def serialize_order(session: Any, order: Order):
    """Build an OrderRead schema without triggering ORM lazy loads."""
    from schemas.order import OrderItemRead, OrderRead

    items = await load_order_items(session, order.id)
    read = OrderRead.model_validate(order)
    return read.model_copy(
        update={
            "items": [OrderItemRead.model_validate(item) for item in items],
        }
    )
