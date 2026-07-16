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

    def summary_message(self) -> str:
        return (
            f"Scanned {self.scanned} stale pending order(s); "
            f"cancelled {self.cancelled}; skipped {self.skipped}."
        )


async def process_stale_pending_orders(session: Any) -> PendingOrderCleanupResult:
    """Cancel pending orders older than ``pending_order_expiry_hours`` and release stock."""
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
            await apply_order_status_change(session, order, "cancelled")
            result.cancelled += 1
            logger.info("Auto-cancelled stale pending order %s", order.id)
        except Exception:
            logger.exception("Failed to auto-cancel pending order %s", order.id)
            result.skipped += 1

    await session.flush()
    return result