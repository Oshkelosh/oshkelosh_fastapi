"""Category lookup helpers."""

from __future__ import annotations

from typing import Any

from models.category import Category


async def resolve_category_id(session: Any, category_id: int | None) -> int | None:
    """Return category_id when the category exists, else None. Raises if invalid."""
    from app.core.exceptions import ValidationError

    if category_id is None:
        return None
    category = await session.get(Category, category_id)
    if category is None:
        raise ValidationError(message=f"Category with id {category_id} not found")
    return category_id
