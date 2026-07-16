"""Native abandoned cart recovery — find stale carts and send reminders."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select

from app.db.base import utc_now
from app.db.connection import mark_instance_dirty
from app.services.lifecycle_events import (
    EVENT_CART_ABANDONED,
    build_cart_abandoned_payload,
    dispatch_lifecycle_event,
)
from app.services.notification_dispatch import dispatch_notification
from app.services.site_settings import get_site_settings, resolve_public_site_url
from models.cart import Cart
from models.cart_item import CartItem
from models.order import Order
from models.product import Product
from models.product_variant import ProductVariant
from models.user import User

logger = logging.getLogger(__name__)


@dataclass
class AbandonedCartRunResult:
    scanned: int = 0
    sent: int = 0
    skipped: int = 0

    def summary_message(self) -> str:
        return f"Scanned {self.scanned} cart(s); sent {self.sent} reminder(s); skipped {self.skipped}."


async def _cart_subtotal_cents(session: Any, cart_id: int) -> int:
    # Cart lines are variant-priced (see commerce.build_cart_pricing_lines).
    stmt = (
        select(func.coalesce(func.sum(ProductVariant.price_cents * CartItem.quantity), 0))
        .select_from(CartItem)
        .join(Product, col(Product.id) == col(CartItem.product_id))
        .join(ProductVariant, col(ProductVariant.id) == col(CartItem.variant_id))
        .where(col(CartItem.cart_id) == cart_id)
        .where(col(Product.status) == "published")
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _user_has_order_since(session: Any, user_id: int, since: datetime) -> bool:
    result = await session.execute(
        select(Order.id)
        .where(col(Order.user_id) == user_id)
        .where(col(Order.created_at) >= since)
        .limit(1)
    )
    return result.first() is not None


async def process_abandoned_carts(session: Any) -> AbandonedCartRunResult:
    """Find eligible stale carts and dispatch abandoned-cart notifications."""
    site = await get_site_settings(session)
    if not site.abandoned_cart_enabled:
        return AbandonedCartRunResult(skipped=0, sent=0, scanned=0)

    delay = timedelta(hours=max(1, site.abandoned_cart_delay_hours))
    max_reminders = max(1, site.abandoned_cart_max_reminders)
    cutoff = utc_now() - delay
    cart_url = f"{resolve_public_site_url(site_settings=site)}/cart"

    result = AbandonedCartRunResult()

    carts_result = await session.execute(
        select(Cart)
        .where(col(Cart.user_id).is_not(None))
        .where(col(Cart.updated_at) <= cutoff)
        .where(col(Cart.abandoned_reminder_count) < max_reminders)
    )
    carts = carts_result.scalars().all()

    for cart in carts:
        result.scanned += 1

        if cart.abandoned_reminded_at is not None:
            if cart.abandoned_reminded_at > cutoff:
                result.skipped += 1
                continue

        user = await session.get(User, cart.user_id)
        if user is None or not user.email or user.banned:
            result.skipped += 1
            continue

        item_count = await session.execute(
            select(func.count())
            .select_from(CartItem)
            .where(col(CartItem.cart_id) == cart.id)
        )
        if int(item_count.scalar_one() or 0) == 0:
            result.skipped += 1
            continue

        if await _user_has_order_since(session, user.id, cart.updated_at):
            result.skipped += 1
            continue

        subtotal_cents = await _cart_subtotal_cents(session, cart.id)
        if subtotal_cents <= 0:
            result.skipped += 1
            continue

        customer_name = user.full_name or user.email
        await dispatch_notification(
            session,
            "cart_abandoned",
            email=user.email,
            phone=user.phone,
            push_token=user.push_token,
            context={
                "cart_url": cart_url,
                "customer_name": customer_name,
                "subtotal_cents": subtotal_cents,
            },
        )
        await dispatch_lifecycle_event(
            EVENT_CART_ABANDONED,
            build_cart_abandoned_payload(
                user=user,
                cart_id=cart.id,
                subtotal_cents=subtotal_cents,
                cart_url=cart_url,
            ),
        )

        cart.abandoned_reminded_at = utc_now()
        cart.abandoned_reminder_count += 1
        mark_instance_dirty(session, cart)
        result.sent += 1

    await session.flush()
    return result
