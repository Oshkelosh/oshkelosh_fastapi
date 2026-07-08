"""Shared admin dashboard statistics for HTML and REST admin surfaces."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlmodel import col, select

from models.order import Order
from models.product import Product
from models.user import User


async def fetch_dashboard_stats(session: Any) -> dict[str, int]:
    """Return core dashboard counters used by HTML and REST admin."""
    total_products = (
        await session.execute(select(func.count()).select_from(Product))
    ).scalar_one()
    total_orders = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    total_revenue = (
        await session.execute(
            select(func.coalesce(func.sum(Order.total_cents), 0)).where(
                col(Order.status).in_(("paid", "shipped", "delivered"))
            )
        )
    ).scalar_one()
    pending_orders = (
        await session.execute(
            select(func.count()).select_from(Order).where(col(Order.status) == "pending")
        )
    ).scalar_one()
    total_users = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar_one()
    return {
        "total_products": total_products or 0,
        "total_orders": total_orders or 0,
        "total_revenue_cents": total_revenue or 0,
        "pending_orders": pending_orders or 0,
        "total_users": total_users or 0,
    }
