"""Product search strategy — core ILIKE with optional search tool delegation."""

from __future__ import annotations

from typing import Any

from sqlmodel import col

from app.services.addons import get_enabled_tools
from models.product import Product


def get_search_tool() -> Any | None:
    """Return the first enabled tool that provides external product search."""
    for tool in get_enabled_tools():
        if getattr(tool, "supports_product_search", lambda: False)():
            return tool
    return None


def apply_core_search_filter(stmt: Any, search: str) -> Any:
    """Apply built-in SQL ILIKE search to a product query."""
    pattern = f"%{search}%"
    return stmt.where(
        col(Product.name).ilike(pattern) | col(Product.description).ilike(pattern)
    )


async def search_products(
    session: Any,
    stmt: Any,
    search: str | None,
    *,
    page: int = 1,
    page_size: int = 20,
    category_id: int | None = None,
    sort: str = "created_at",
    order: str = "desc",
) -> Any | None:
    """Delegate search to an enabled tool, or return None to use core ILIKE."""
    if not search or not search.strip():
        return None

    tool = get_search_tool()
    if tool is None:
        return None

    return await tool.search_products(
        session,
        search.strip(),
        page=page,
        page_size=page_size,
        category_id=category_id,
        sort=sort,
        order=order,
    )
