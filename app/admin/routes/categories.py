from typing import Any, Optional

from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    Form,
    Query,
    RedirectResponse,
    Request,
    _common_ctx,
    _render_error,
    _require_csrf,
    _template,
    col,
    func,
    mark_instance_dirty,
    require_admin_session,
    select,
    set_flash_cookie,
)

router = APIRouter()


async def _load_all_categories(db):
    from models.category import Category

    result = await db.execute(select(Category).order_by(col(Category.sort_order).asc(), col(Category.name).asc()))
    return result.scalars().all()


async def _get_category_by_slug(db, slug: str):
    from models.category import Category

    result = await db.execute(select(Category).where(col(Category.slug) == slug))
    return result.scalar_one_or_none()


def _parent_options(categories: list[Any], *, exclude_id: int | None = None) -> list[Any]:
    if exclude_id is None:
        return categories
    return [cat for cat in categories if cat.id != exclude_id]


async def _render_category_form(
    request: Request,
    *,
    title: str,
    category: Any = None,
    action_url: str,
    form_error: str | None = None,
    draft: Optional[dict[str, Any]] = None,
    db=None,
):
    parent_options = []
    if db is not None:
        try:
            parent_options = _parent_options(
                await _load_all_categories(db),
                exclude_id=category.id if category else None,
            )
        except Exception:
            pass

    return _template(
        "category_form.html",
        **_common_ctx(request, title),
        category=category,
        action_url=action_url,
        form_error=form_error,
        draft=draft,
        parent_options=parent_options,
    )

@router.get("/categories")
async def admin_categories_list(
    request: Request,
    page: int = Query(1, ge=1),
    db=Depends(require_admin_session),
):
    """List categories with pagination."""
    from models.category import Category

    PAGE_SIZE = 25
    offset = (page - 1) * PAGE_SIZE
    categories = []
    total = 0

    if db is not None:
        try:
            count_result = await db.execute(select(func.count(Category.id)))
            total = count_result.scalar() or 0
            result = await db.execute(
                select(Category)
                .order_by(col(Category.sort_order).asc())
                .offset(offset)
                .limit(PAGE_SIZE)
            )
            categories = result.scalars().all()
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return _template(
        "categories.html",
        **_common_ctx(request, "Categories"),
        categories=categories,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
    )


@router.get("/categories/new")
async def admin_category_new(request: Request, db=Depends(require_admin_session)):
    """Show the create-category form."""
    return await _render_category_form(
        request,
        title="New Category",
        action_url="/admin/categories",
        db=db,
    )


@router.post("/categories")
async def admin_category_create(
    request: Request,
    name: str = Form(..., max_length=L.NAME_LEN),
    slug: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    meta_title: str = Form("", max_length=255),
    meta_description: str = Form("", max_length=500),
    parent_id: Optional[int] = Form(None),
    sort_order: int = Form(0),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a category."""
    from models.category import Category

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    existing = await _get_category_by_slug(db, slug)
    if existing is not None:
        return await _render_category_form(
            request,
            title="New Category",
            action_url="/admin/categories",
            form_error=f"Category with slug '{slug}' already exists",
            draft={
                "name": name,
                "slug": slug,
                "description": description,
                "meta_title": meta_title,
                "meta_description": meta_description,
                "parent_id": parent_id,
                "sort_order": sort_order,
            },
            db=db,
        )

    if parent_id is not None:
        parent = await db.get(Category, parent_id)
        if parent is None:
            return await _render_category_form(
                request,
                title="New Category",
                action_url="/admin/categories",
                form_error="Parent category not found",
                draft={
                    "name": name,
                    "slug": slug,
                    "description": description,
                    "meta_title": meta_title,
                    "meta_description": meta_description,
                    "parent_id": parent_id,
                    "sort_order": sort_order,
                },
                db=db,
            )

    cat = Category(
        name=name,
        slug=slug,
        description=description or None,
        meta_title=meta_title or None,
        meta_description=meta_description or None,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    db.add(cat)
    await db.flush()
    from app.services.category_defaults import apply_category_creation_defaults
    from app.services.site_settings import get_site_settings

    site_settings = await get_site_settings(db)
    store_name = site_settings.store_name or "Store"
    await apply_category_creation_defaults(db, cat, store_name=store_name)
    await db.commit()
    await db.refresh(cat)

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="create",
        resource_type="category",
        resource_id=cat.id,
        changes={"name": cat.name, "slug": cat.slug},
        ip_address=ip_address,
        detail=f"Created category '{cat.name}'",
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/categories", status_code=302)
    set_flash_cookie(resp, f"Category '{cat.name}' created")
    return resp


@router.get("/categories/{slug}/edit")
async def admin_category_edit(request: Request, slug: str, db=Depends(require_admin_session)):
    """Show the edit-category form."""
    if not db:
        return _render_error(request, "Database unavailable")

    category = await _get_category_by_slug(db, slug)
    if category is None:
        return _render_error(request, "Category not found", status_code=404)

    return await _render_category_form(
        request,
        title=f"Edit: {category.name}",
        category=category,
        action_url=f"/admin/categories/{slug}/edit",
        db=db,
    )


@router.post("/categories/{slug}/edit")
async def admin_category_update(
    request: Request,
    slug: str,
    name: str = Form(..., max_length=L.NAME_LEN),
    new_slug: str = Form(..., max_length=L.NAME_LEN, alias="slug"),
    description: str = Form("", max_length=L.TEXT_LEN),
    meta_title: str = Form("", max_length=255),
    meta_description: str = Form("", max_length=500),
    parent_id: Optional[int] = Form(None),
    sort_order: int = Form(0),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Update a category."""
    from models.category import Category

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    category = await _get_category_by_slug(db, slug)
    if category is None:
        return _render_error(request, "Category not found", status_code=404)

    draft = {
        "name": name,
        "slug": new_slug,
        "description": description,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "parent_id": parent_id,
        "sort_order": sort_order,
    }

    if new_slug != category.slug:
        existing = await _get_category_by_slug(db, new_slug)
        if existing is not None:
            return await _render_category_form(
                request,
                title=f"Edit: {category.name}",
                category=category,
                action_url=f"/admin/categories/{slug}/edit",
                form_error=f"Category with slug '{new_slug}' already exists",
                draft=draft,
                db=db,
            )

    if parent_id is not None:
        if parent_id == category.id:
            return await _render_category_form(
                request,
                title=f"Edit: {category.name}",
                category=category,
                action_url=f"/admin/categories/{slug}/edit",
                form_error="A category cannot be its own parent",
                draft=draft,
                db=db,
            )
        parent = await db.get(Category, parent_id)
        if parent is None:
            return await _render_category_form(
                request,
                title=f"Edit: {category.name}",
                category=category,
                action_url=f"/admin/categories/{slug}/edit",
                form_error="Parent category not found",
                draft=draft,
                db=db,
            )

    before = {"name": category.name, "slug": category.slug, "parent_id": category.parent_id}
    category.name = name
    category.slug = new_slug
    category.description = description or None
    category.meta_title = meta_title or None
    category.meta_description = meta_description or None
    category.parent_id = parent_id
    category.sort_order = sort_order
    mark_instance_dirty(db, category)

    await db.commit()
    await db.refresh(category)

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="category",
        resource_id=category.id,
        changes={"before": before, "after": {"name": category.name, "slug": category.slug, "parent_id": category.parent_id}},
        ip_address=ip_address,
        detail=f"Updated category '{category.name}'",
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/categories", status_code=302)
    set_flash_cookie(resp, f"Category '{category.name}' updated")
    return resp


@router.post("/categories/{slug}/delete")
async def admin_category_delete(
    request: Request,
    slug: str,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Delete a category."""
    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    category = await _get_category_by_slug(db, slug)
    if category is None:
        return _render_error(request, "Category not found", status_code=404)

    category_name = category.name
    category_id = category.id

    await db.delete(category)
    await db.commit()

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="delete",
        resource_type="category",
        resource_id=category_id,
        changes={"name": category_name, "slug": slug},
        ip_address=ip_address,
        detail=f"Deleted category '{category_name}'",
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/categories", status_code=302)
    set_flash_cookie(resp, f"Category '{category_name}' deleted")
    return resp

