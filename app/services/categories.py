"""Category lookup helpers."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from app.core.exceptions import NotFound, ValidationError
from models.category import Category


async def resolve_category_id(session: Any, category_id: int | None) -> int | None:
    """Return category_id when the category exists, else None. Raises if invalid."""
    if category_id is None:
        return None
    category = await session.get(Category, category_id)
    if category is None:
        raise ValidationError(message=f"Category with id {category_id} not found")
    return category_id


async def get_category_by_slug(session: Any, slug: str) -> Category | None:
    """Load a category by slug."""
    result = await session.execute(select(Category).where(col(Category.slug) == slug))
    return result.scalar_one_or_none()


async def require_category_by_slug(session: Any, slug: str) -> Category:
    """Load a category by slug or raise NotFound."""
    category = await get_category_by_slug(session, slug)
    if category is None:
        raise NotFound(resource_name="Category", resource_id=slug)
    return category


async def ensure_category_slug_available(
    session: Any,
    slug: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """Raise when the slug already belongs to another category."""
    category = await get_category_by_slug(session, slug)
    if category is not None and category.id != exclude_id:
        raise ValidationError(message=f"Category with slug '{slug}' already exists")


async def validate_category_parent(session: Any, category_id: int, parent_id: int | None) -> None:
    """Validate a category parent reference for create/update flows."""
    if parent_id is None:
        return
    if parent_id == category_id:
        raise ValidationError(message="A category cannot be its own parent")
    parent = await session.get(Category, parent_id)
    if parent is None:
        raise NotFound(resource_name="Category", resource_id=parent_id)
