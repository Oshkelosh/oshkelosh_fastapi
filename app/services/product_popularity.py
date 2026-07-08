"""Product popularity: units_sold counter and units-per-day ranking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import case, func
from sqlalchemy.sql.elements import ColumnElement

from models.order_item import OrderItem
from models.product import Product


def compute_popularity_score(units_sold: int, created_at: datetime) -> float:
    """Return units_sold / max(1, age in whole days since created_at)."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    age_days = max(1, (now - created_at).days)
    return units_sold / age_days


def popularity_order_clause(order: str) -> ColumnElement[Any]:
    """SQL ORDER BY expression for sort=popularity (SQLite / D1 julianday)."""
    age_days = func.julianday("now") - func.julianday(Product.created_at)
    age_days_clamped = case((age_days < 1.0, 1.0), else_=age_days)
    popularity = Product.units_sold / age_days_clamped
    if order == "desc":
        return popularity.desc()
    return popularity.asc()


async def increment_product_units_sold(
    session: Any,
    items: Sequence[OrderItem],
) -> None:
    """Bump units_sold for each order line with a linked product."""
    from sqlalchemy import text

    for item in items:
        if item.product_id is None or item.quantity <= 0:
            continue
        product_id = item.product_id
        quantity = item.quantity
        if hasattr(session, "execute_raw"):
            await session.execute_raw(
                "UPDATE products SET units_sold = units_sold + ? WHERE id = ?",
                [quantity, product_id],
            )
        else:
            await session.execute(
                text(
                    "UPDATE products SET units_sold = units_sold + :qty WHERE id = :id"
                ),
                {"qty": quantity, "id": product_id},
            )
        product = await session.get(Product, product_id)
        if product is not None:
            await session.refresh(product)


async def decrement_product_units_sold(
    session: Any,
    items: Sequence[OrderItem],
) -> None:
    """Reduce units_sold when a paid order is cancelled."""
    from sqlalchemy import text

    for item in items:
        if item.product_id is None or item.quantity <= 0:
            continue
        product_id = item.product_id
        quantity = item.quantity
        if hasattr(session, "execute_raw"):
            await session.execute_raw(
                "UPDATE products SET units_sold = MAX(0, units_sold - ?) WHERE id = ?",
                [quantity, product_id],
            )
        else:
            await session.execute(
                text(
                    "UPDATE products SET units_sold = MAX(0, units_sold - :qty) WHERE id = :id"
                ),
                {"qty": quantity, "id": product_id},
            )
        product = await session.get(Product, product_id)
        if product is not None:
            await session.refresh(product)