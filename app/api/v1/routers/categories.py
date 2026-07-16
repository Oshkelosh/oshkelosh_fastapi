"""Category endpoints.

Public tree-structured category listing for the storefront.
Category administration lives in the server-rendered admin panel.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import col, select

from app.core.exceptions import NotFound
from app.db.connection import get_session
from models.category import Category
from schemas.category import CategoryRead

router = APIRouter(prefix="/categories", tags=["categories"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _category_read(cat: Category, *, children: list[CategoryRead] | None = None) -> CategoryRead:
    """Build CategoryRead without triggering async relationship loads."""
    return CategoryRead(**{**cat.model_dump(), "children": children or []})


async def _load_category_read(session, category: Category) -> CategoryRead:
    """Return a category with direct children loaded explicitly."""
    result = await session.execute(
        select(Category)
        .where(col(Category.parent_id) == category.id)
        .order_by(Category.sort_order.asc(), Category.name.asc())
    )
    children = [_category_read(child) for child in result.scalars().all()]
    return _category_read(category, children=children)


def _build_tree(categories: List[Category]) -> List[dict]:
    """Build a nested parent/children tree from a flat list of categories."""
    by_id: dict[int, dict] = {}
    roots: List[dict] = []

    for cat in categories:
        node: dict = {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "parent_id": cat.parent_id,
            "sort_order": cat.sort_order,
            "created_at": cat.created_at,
            "updated_at": cat.updated_at,
            "children": [],
        }
        by_id[cat.id] = node

    for cat in categories:
        node = by_id[cat.id]
        if cat.parent_id is not None and cat.parent_id in by_id:
            by_id[cat.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


# ------------------------------------------------------------------
# Public endpoints
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=dict,
    summary="List categories",
    description="Return categories in a hierarchical tree structure.",
)
async def list_categories(
    session=Depends(get_session),
) -> dict:
    """Return all categories as a tree."""
    result = await session.execute(
        select(Category).order_by(Category.sort_order.asc(), Category.name.asc())
    )
    categories = result.scalars().all()
    return {"items": _build_tree(categories), "total": len(categories)}


@router.get(
    "/{category_slug}",
    response_model=CategoryRead,
    summary="Get category detail",
    description="Return the detail of a single category with its children.",
)
async def get_category(
    category_slug: str,
    session=Depends(get_session),
) -> CategoryRead:
    """Return a single category's detail."""
    result = await session.execute(
        select(Category).where(col(Category.slug) == category_slug)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFound(resource_name="Category", resource_id=category_slug)
    return await _load_category_read(session, category)


