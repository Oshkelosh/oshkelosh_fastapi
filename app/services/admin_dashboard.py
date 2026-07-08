"""Shared admin dashboard statistics for HTML and REST admin surfaces."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import col, select

from models.order import Order
from models.product import Product
from models.user import User

REVENUE_STATUSES = ("paid", "shipped", "delivered")


def _normalize_anchor_day(anchor: datetime | date | None = None) -> date:
    if anchor is None:
        return datetime.now(timezone.utc).date()
    if isinstance(anchor, datetime):
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        else:
            anchor = anchor.astimezone(timezone.utc)
        return anchor.date()
    return anchor


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
                col(Order.status).in_(REVENUE_STATUSES)
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


async def fetch_revenue_trend(
    session: Any,
    *,
    days: int = 30,
    anchor: datetime | date | None = None,
) -> dict[str, Any]:
    """Return a zero-filled daily revenue series for the admin dashboard."""
    if days < 1:
        raise ValueError("days must be at least 1")

    end_day = _normalize_anchor_day(anchor)
    start_day = end_day - timedelta(days=days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)

    stmt = (
        select(Order.created_at, Order.total_cents)
        .where(col(Order.status).in_(REVENUE_STATUSES))
        .where(col(Order.created_at) >= start_at)
        .order_by(col(Order.created_at).asc())
    )
    rows = (await session.execute(stmt)).all()

    revenue_by_day = {start_day + timedelta(days=offset): 0 for offset in range(days)}
    for created_at, total_cents in rows:
        created_day = created_at.date()
        if start_day <= created_day <= end_day:
            revenue_by_day[created_day] += total_cents or 0

    points = [
        {"date": day.isoformat(), "revenue_cents": revenue_by_day[day]}
        for day in sorted(revenue_by_day)
    ]
    totals = [point["revenue_cents"] for point in points]
    return {
        "days": points,
        "max_cents": max(totals, default=0),
        "total_cents": sum(totals),
    }
