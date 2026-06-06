"""Category endpoints.

Provides a tree-structured public listing of categories as well as
admin CRUD operations.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app.core.dependencies import CurrentUser, get_admin_user, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session, mark_instance_dirty
from models.category import Category
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

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
) -> Category:
    """Return a single category's detail."""
    result = await session.execute(
        select(Category).where(col(Category.slug) == category_slug)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFound(resource_name="Category", resource_id=category_slug)
    return category


# ------------------------------------------------------------------
# Admin endpoints
# ------------------------------------------------------------------

@router.post(
    "",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create category",
    description="Create a new category (admin only).",
)
async def create_category(
    body: CategoryCreate,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> Category:
    """Create a new category."""
    # Check for duplicate slug
    existing = await session.execute(
        select(Category).where(col(Category.slug) == body.slug)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValidationError(message=f"Category with slug '{body.slug}' already exists")

    # Validate parent exists
    if body.parent_id is not None:
        parent = await session.get(Category, body.parent_id)
        if parent is None:
            raise NotFound(resource_name="Category", resource_id=body.parent_id)

    category = Category(
        name=body.name,
        slug=body.slug,
        description=body.description,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
    )
    session.add(category)
    await session.flush()
    await session.refresh(category)
    return category


@router.patch(
    "/{category_slug}",
    response_model=CategoryRead,
    summary="Update category",
    description="Update an existing category (admin only).",
)
async def update_category(
    category_slug: str,
    body: CategoryUpdate,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> Category:
    """Update an existing category."""
    result = await session.execute(
        select(Category).where(col(Category.slug) == category_slug)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFound(resource_name="Category", resource_id=category_slug)

    update_data = body.model_dump(exclude_unset=True)

    # Validate new slug uniqueness
    if "slug" in update_data and update_data["slug"] != category.slug:
        existing = await session.execute(
            select(Category).where(col(Category.slug) == update_data["slug"])
        )
        if existing.scalar_one_or_none() is not None:
            raise ValidationError(message=f"Category with slug '{update_data['slug']}' already exists")

    # Validate parent exists
    if "parent_id" in update_data and update_data["parent_id"] is not None:
        if update_data["parent_id"] == category.id:
            raise ValidationError(message="A category cannot be its own parent")
        parent = await session.get(Category, update_data["parent_id"])
        if parent is None:
            raise NotFound(resource_name="Category", resource_id=update_data["parent_id"])

    for key, value in update_data.items():
        setattr(category, key, value)
    mark_instance_dirty(session, category)

    await session.flush()
    await session.refresh(category)
    return category


@router.delete(
    "/{category_slug}",
    response_model=dict,
    summary="Delete category",
    description="Delete a category (admin only).",
)
async def delete_category(
    category_slug: str,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
) -> dict:
    """Delete a category."""
    result = await session.execute(
        select(Category).where(col(Category.slug) == category_slug)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise NotFound(resource_name="Category", resource_id=category_slug)

    # Check if this category has children – cascade will handle deletion
    children_result = await session.execute(
        select(Category).where(col(Category.parent_id) == category.id)
    )
    children = children_result.scalars().all()
    if children:
        # Children will be cascade-deleted; warn the caller
        pass

    await session.delete(category)
    return {"message": f"Category '{category_slug}' deleted"}
