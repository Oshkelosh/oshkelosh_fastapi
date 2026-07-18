"""ManualSupplier persistence.

Core owns the ``ManualSupplier`` model and its queries; the manual supplier
addon only renders UI and fulfillment payloads on top of these.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from models.manual_supplier import ManualSupplier


async def list_manual_suppliers(
    session: Any, *, active_only: bool = False
) -> list[ManualSupplier]:
    stmt = select(ManualSupplier).order_by(col(ManualSupplier.name).asc())
    if active_only:
        stmt = stmt.where(col(ManualSupplier.is_active) == True)  # noqa: E712
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_manual_supplier(session: Any, slug: str) -> ManualSupplier | None:
    result = await session.execute(
        select(ManualSupplier).where(col(ManualSupplier.slug) == slug)
    )
    return result.scalar_one_or_none()
