"""Cancel stale pending orders and restore reserved inventory."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlmodel import col, select

from app.config import settings
from app.db.base import utc_now
from app.services.commerce import apply_order_status_change, load_order_items
from models.order import Order

logger = logging.getLogger(__name__)


@dataclass
class PendingOrderCleanupResult:
    scanned: int = 0
    cancelled: int = 0
    skipped: int = 0
    reconciled: int = 0

    def summary_message(self) -> str:
        return (
            f"Scanned {self.scanned} stale pending order(s); "
            f"cancelled {self.cancelled}; reconciled {self.reconciled} paid; "
            f"skipped {self.skipped}."
        )


_PAID_STATUSES = frozenset({"paid", "succeeded", "completed", "captured", "complete"})


async def _order_was_charged(order: Order) -> bool | None:
    """Ask the PSP whether a pending order's payment actually completed.

    Returns True if charged, False if provably not charged, None when the
    status cannot be determined (missing addon, API error) — in which case the
    caller must not cancel.
    """
    if not order.payment_id or not order.payment_processor_id:
        return False
    from app.addons.registry import addon_registry

    addon = addon_registry.get(order.payment_processor_id)
    if addon is None or not getattr(addon, "is_enabled", False):
        return None
    try:
        status = await addon.get_payment_status(order.payment_id)
    except Exception:
        logger.exception(
            "Could not check payment status for pending order %s", order.id
        )
        return None
    value = str(status.get("status", "")).strip().lower()
    if value in ("error", "unknown", ""):
        return None
    return value in _PAID_STATUSES


async def process_stale_pending_orders(session: Any) -> PendingOrderCleanupResult:
    """Cancel stale unpaid pending orders; never cancel one the PSP charged."""
    hours = max(1, settings.pending_order_expiry_hours)
    cutoff = utc_now() - timedelta(hours=hours)
    result = PendingOrderCleanupResult()

    stmt = (
        select(Order)
        .where(col(Order.status) == "pending")
        .where(col(Order.created_at) < cutoff)
        .order_by(col(Order.created_at))
    )
    query = await session.execute(stmt)
    orders = list(query.scalars().all())
    result.scanned = len(orders)

    for order in orders:
        try:
            charged = await _order_was_charged(order)
            if charged is None:
                logger.warning(
                    "Skipping stale pending order %s: payment status unknown", order.id
                )
                result.skipped += 1
                continue
            if charged:
                # The webhook was lost or delayed; reconcile to paid instead of
                # cancelling a charged order.
                from app.services.payments import complete_order_payment

                await complete_order_payment(
                    session,
                    order.id,
                    processor_id=order.payment_processor_id or "",
                    payment_id=order.payment_id,
                )
                result.reconciled += 1
                logger.info("Reconciled charged pending order %s to paid", order.id)
                continue
            await apply_order_status_change(session, order, "cancelled")
            result.cancelled += 1
            logger.info("Auto-cancelled stale pending order %s", order.id)
        except Exception:
            logger.exception("Failed to auto-cancel pending order %s", order.id)
            result.skipped += 1

    await session.flush()
    return result