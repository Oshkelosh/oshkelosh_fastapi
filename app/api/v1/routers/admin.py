"""Admin API endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from app.core.dependencies import CurrentUser, get_admin_user
from app.core.exceptions import NotFound, ValidationError
from app.core.security import hash_password
from app.db.connection import get_session, mark_instance_dirty
from app.services.audit import log_change
from app.services.commerce import VALID_TRANSITIONS, apply_order_status_change, serialize_order
from app.services.categories import resolve_category_id
from app.services.product_defaults import apply_product_creation_defaults, validate_api_product_update
from app.services.product_images import build_product_read, build_product_reads
from app.services.product_slugs import (
    ensure_product_slug,
    raise_friendly_product_integrity_error,
    sku_exists,
    slug_exists,
)
from app.services.site_settings import get_site_settings
from app.services.user_accounts import mark_user_verified
from models.addon_config import AddonConfig
from models.category import Category
from models.order import Order
from models.product import Product
from models.user import User
from schemas.base import PaginatedResponse
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from schemas.order import OrderRead, OrderUpdateStatus
from schemas.product import ProductCreate, ProductRead, ProductUpdate
from schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


def _category_read(cat: Category) -> CategoryRead:
    """Build CategoryRead without triggering async relationship loads."""
    return CategoryRead(**{**cat.model_dump(), "children": []})


def _api_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class DashboardStats(BaseModel):
    total_products: int
    total_orders: int
    total_revenue_cents: int
    pending_orders: int
    total_users: int


class SupplierCatalogSyncRequest(BaseModel):
    import_status: str = "draft"
    archive_missing: bool = False
    addon_ids: list[str] | None = None


class SupplierCatalogSyncResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    archived: int
    errors: list[str]
    message: str


class HealthCheckRead(BaseModel):
    id: str
    label: str
    status: str
    detail: str = ""


class HealthSummaryRead(BaseModel):
    overall: str
    checks: list[HealthCheckRead]


class IntegrationSummaryRead(BaseModel):
    payment_name: str | None = None
    frontend_name: str | None = None
    notification_channels: list[str] = []
    enabled_supplier_count: int = 0
    syncable_supplier_count: int = 0


class SupplierSyncStatusRead(BaseModel):
    addon_id: str
    addon_name: str
    last_sync_at: datetime | None = None


class SupplierSummaryRead(BaseModel):
    syncable_suppliers: list[SupplierSyncStatusRead]
    active_job_id: str | None = None


class DashboardOverviewRead(BaseModel):
    stats: DashboardStats
    health: HealthSummaryRead
    integrations: IntegrationSummaryRead
    supplier_summary: SupplierSummaryRead


class BackgroundJobRead(BaseModel):
    id: str
    job_type: str
    status: str
    progress: dict | None = None
    payload: dict | None = None
    error: str | None = None
    percent_complete: int = 0
    created_at: datetime
    updated_at: datetime


class StartSupplierSyncJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


async def _paginate(session, stmt, page: int, page_size: int):
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one() or 0
    offset = (page - 1) * page_size
    items_result = await session.execute(stmt.offset(offset).limit(page_size))
    items = items_result.scalars().all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedResponse(
        items=list(items),
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def _fetch_dashboard_stats(session) -> DashboardStats:
    from app.services.admin_dashboard import fetch_dashboard_stats

    stats = await fetch_dashboard_stats(session)
    return DashboardStats(**stats)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> DashboardStats:
    """Return admin dashboard statistics."""
    return await _fetch_dashboard_stats(session)


async def _build_dashboard_overview(session) -> DashboardOverviewRead:
    from app.services.background_jobs import get_active_supplier_sync_job
    from app.services.supplier_catalog_sync import get_last_sync_times, list_syncable_suppliers
    from app.services.system_health import build_health_summary, build_integration_summary

    stats = await _fetch_dashboard_stats(session)
    health = await build_health_summary(session)
    integrations = await build_integration_summary()
    last_sync = await get_last_sync_times(session)
    syncable = list_syncable_suppliers()
    active_job = await get_active_supplier_sync_job(session)

    return DashboardOverviewRead(
        stats=stats,
        health=HealthSummaryRead(
            overall=health.overall,
            checks=[
                HealthCheckRead(
                    id=c.id,
                    label=c.label,
                    status=c.status,
                    detail=c.detail,
                )
                for c in health.checks
            ],
        ),
        integrations=IntegrationSummaryRead(
            payment_name=integrations.payment_name,
            frontend_name=integrations.frontend_name,
            notification_channels=integrations.notification_channels,
            enabled_supplier_count=integrations.enabled_supplier_count,
            syncable_supplier_count=integrations.syncable_supplier_count,
        ),
        supplier_summary=SupplierSummaryRead(
            syncable_suppliers=[
                SupplierSyncStatusRead(
                    addon_id=addon.addon_id,
                    addon_name=addon.addon_name,
                    last_sync_at=last_sync.get(addon.addon_id),
                )
                for addon in syncable
            ],
            active_job_id=active_job.id if active_job else None,
        ),
    )


@router.get("/health", response_model=HealthSummaryRead)
async def admin_health_summary(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> HealthSummaryRead:
    """Return infrastructure and store integration health."""
    from app.services.system_health import build_health_summary

    health = await build_health_summary(session)
    return HealthSummaryRead(
        overall=health.overall,
        checks=[
            HealthCheckRead(id=c.id, label=c.label, status=c.status, detail=c.detail)
            for c in health.checks
        ],
    )


@router.get("/dashboard", response_model=DashboardOverviewRead)
async def admin_dashboard_overview(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> DashboardOverviewRead:
    """Return dashboard stats plus health, integrations, and supplier sync summary."""
    return await _build_dashboard_overview(session)


@router.get("/users", response_model=PaginatedResponse[UserRead])
async def admin_list_users(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    banned: bool | None = Query(None),
    verified: bool | None = Query(None),
):
    """List all users (admin)."""
    stmt = select(User).order_by(col(User.created_at).desc())
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            col(User.email).ilike(pattern) | col(User.full_name).ilike(pattern)
        )
    if banned is not None:
        stmt = stmt.where(col(User.banned) == banned)
    if verified is not None:
        stmt = stmt.where(col(User.verified) == verified)
    return await _paginate(session, stmt, page, page_size)


@router.get("/users/{user_id}", response_model=UserRead)
async def admin_get_user(
    user_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> User:
    """Get a single user (admin)."""
    user = await session.get(User, user_id)
    if not user:
        raise NotFound(resource_name="User", resource_id=user_id)
    return user


@router.post("/users", response_model=UserRead, status_code=201)
async def admin_create_user(
    request: Request,
    data: UserCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> User:
    """Create a user account (admin)."""
    existing = await session.execute(
        select(User).where(col(User.email) == data.email)
    )
    if existing.first() is not None:
        raise ValidationError(message="A user with this email already exists")

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        default_shipping_address=data.default_shipping_address,
        banned=data.banned,
        verified=data.verified,
        is_admin=data.is_admin,
    )
    if user.verified and user.verified_at is None:
        mark_user_verified(user)

    session.add(user)
    await session.flush()
    await session.refresh(user)
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="create",
        resource_type="user",
        resource_id=user.id,
        ip_address=_api_client_ip(request),
    )
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def admin_update_user(
    request: Request,
    user_id: int,
    data: UserUpdate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> User:
    """Update a user account (admin)."""
    user = await session.get(User, user_id)
    if not user:
        raise NotFound(resource_name="User", resource_id=user_id)

    before = user.model_dump()
    updates = data.model_dump(exclude_unset=True)
    password = updates.pop("password", None)
    verified_set = updates.pop("verified", None)
    for key, value in updates.items():
        setattr(user, key, value)

    if password is not None:
        user.password_hash = hash_password(password)

    if verified_set is True:
        mark_user_verified(user)
    elif verified_set is False:
        user.verified = False
        user.verified_at = None

    mark_instance_dirty(session, user)
    await session.flush()
    await session.refresh(user)
    from app.services.audit import diff_fields

    await log_change(
        session,
        actor_user_id=current_user.id,
        action="update",
        resource_type="user",
        resource_id=user.id,
        changes=diff_fields(before, user.model_dump(), keys=set(updates.keys())),
        ip_address=_api_client_ip(request),
    )
    return user


@router.get("/products", response_model=PaginatedResponse[ProductRead])
async def admin_list_products(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    """List all products (admin)."""
    stmt = select(Product).order_by(col(Product.created_at).desc())
    if status:
        stmt = stmt.where(col(Product.status) == status)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            col(Product.name).ilike(pattern) | col(Product.description).ilike(pattern)
        )
    page_result = await _paginate(session, stmt, page, page_size)
    return PaginatedResponse(
        items=await build_product_reads(session, list(page_result.items)),
        page=page_result.page,
        page_size=page_result.page_size,
        total=page_result.total,
        total_pages=page_result.total_pages,
    )


@router.post("/products", response_model=ProductRead, status_code=201)
async def admin_create_product(
    request: Request,
    data: ProductCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> ProductRead:
    """Create a new product."""
    if data.sku and await sku_exists(session, data.sku):
        raise ValidationError(message=f"Product with SKU '{data.sku}' already exists")
    if data.slug and await slug_exists(session, data.slug):
        raise ValidationError(message=f"Product with slug '{data.slug}' already exists")

    category_id = await resolve_category_id(session, data.category_id)
    product = Product(
        **data.model_dump(exclude={"created_by", "category_id"}),
        category_id=category_id,
        created_by=current_user.id,
    )
    session.add(product)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise_friendly_product_integrity_error(exc)
    site_settings = await get_site_settings(session)
    store_name = site_settings.store_name or "Store"
    await apply_product_creation_defaults(
        session,
        product,
        store_name=store_name,
        preferred_slug=data.slug,
    )
    mark_instance_dirty(session, product)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise_friendly_product_integrity_error(exc)
    await session.refresh(product)
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="create",
        resource_type="product",
        resource_id=product.id,
        ip_address=_api_client_ip(request),
    )
    return await build_product_read(session, product)


@router.patch("/products/{product_id}", response_model=ProductRead)
async def admin_update_product(
    request: Request,
    product_id: int,
    data: ProductUpdate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> ProductRead:
    """Update a product."""
    product = await session.get(Product, product_id)
    if not product:
        raise NotFound(resource_name="Product", resource_id=product_id)

    update_data = data.model_dump(exclude_unset=True)
    preferred_slug = update_data.pop("slug", None)
    validate_api_product_update(product, update_data)
    if preferred_slug and await slug_exists(session, preferred_slug, exclude_id=product_id):
        raise ValidationError(message=f"Product with slug '{preferred_slug}' already exists")

    if "category_id" in update_data:
        update_data["category_id"] = await resolve_category_id(session, update_data["category_id"])

    before = product.model_dump()
    for key, value in update_data.items():
        setattr(product, key, value)
    if preferred_slug:
        await ensure_product_slug(session, product, preferred=preferred_slug)
    mark_instance_dirty(session, product)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise_friendly_product_integrity_error(exc)
    await session.refresh(product)
    from app.services.audit import diff_fields

    await log_change(
        session,
        actor_user_id=current_user.id,
        action="update",
        resource_type="product",
        resource_id=product.id,
        changes=diff_fields(before, product.model_dump(), keys=set(update_data.keys())),
        ip_address=_api_client_ip(request),
    )
    return await build_product_read(session, product)


@router.delete("/products/{product_id}", status_code=204)
async def admin_delete_product(
    request: Request,
    product_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> None:
    """Delete a product."""
    from app.services.product_slugs import product_has_order_items

    product = await session.get(Product, product_id)
    if not product:
        raise NotFound(resource_name="Product", resource_id=product_id)
    if await product_has_order_items(session, product_id):
        raise ValidationError(
            message=f"Cannot delete product '{product.name}': it appears on existing orders"
        )
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="delete",
        resource_type="product",
        resource_id=product_id,
        ip_address=_api_client_ip(request),
    )
    await session.delete(product)


@router.get("/categories", response_model=PaginatedResponse[CategoryRead])
async def admin_list_categories(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all categories."""
    stmt = select(Category).order_by(col(Category.sort_order))
    return await _paginate(session, stmt, page, page_size)


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def admin_create_category(
    request: Request,
    data: CategoryCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Category:
    """Create a category."""
    cat = Category(**data.model_dump())
    session.add(cat)
    await session.flush()
    from app.services.category_defaults import apply_category_creation_defaults

    site_settings = await get_site_settings(session)
    store_name = site_settings.store_name or "Store"
    await apply_category_creation_defaults(session, cat, store_name=store_name)
    await session.flush()
    await session.refresh(cat)
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="create",
        resource_type="category",
        resource_id=cat.id,
        ip_address=_api_client_ip(request),
    )
    return _category_read(cat)


@router.patch("/categories/{slug}", response_model=CategoryRead)
async def admin_update_category(
    request: Request,
    slug: str,
    data: CategoryUpdate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Category:
    """Update a category."""
    result = await session.execute(select(Category).where(col(Category.slug) == slug))
    cat = result.scalar_one_or_none()
    if not cat:
        raise NotFound(resource_name="Category", resource_id=slug)
    before = cat.model_dump()
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cat, key, value)
    mark_instance_dirty(session, cat)
    await session.flush()
    await session.refresh(cat)
    from app.services.audit import diff_fields

    await log_change(
        session,
        actor_user_id=current_user.id,
        action="update",
        resource_type="category",
        resource_id=cat.id,
        changes=diff_fields(before, cat.model_dump(), keys=set(update_data.keys())),
        ip_address=_api_client_ip(request),
    )
    return _category_read(cat)


@router.delete("/categories/{slug}", status_code=204)
async def admin_delete_category(
    request: Request,
    slug: str,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> None:
    """Delete a category."""
    result = await session.execute(select(Category).where(col(Category.slug) == slug))
    cat = result.scalar_one_or_none()
    if not cat:
        raise NotFound(resource_name="Category", resource_id=slug)
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="delete",
        resource_type="category",
        resource_id=cat.id,
        ip_address=_api_client_ip(request),
    )
    await session.delete(cat)


@router.get("/orders", response_model=PaginatedResponse[OrderRead])
async def admin_list_orders(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    """List all orders (admin)."""
    stmt = select(Order).order_by(col(Order.created_at).desc())
    if status:
        stmt = stmt.where(col(Order.status) == status)
    return await _paginate(session, stmt, page, page_size)


@router.patch("/orders/{order_id}/status", response_model=OrderRead)
async def admin_update_order_status(
    request: Request,
    order_id: int,
    data: OrderUpdateStatus,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> Order:
    """Update an order's status."""
    from app.services.commerce import apply_order_status_change, serialize_order

    order = await session.get(Order, order_id)
    if not order:
        raise NotFound(resource_name="Order", resource_id=order_id)

    old_status = order.status
    allowed = VALID_TRANSITIONS.get(order.status, set())
    if data.status not in allowed:
        raise ValidationError(
            message=f"Cannot transition from '{order.status}' to '{data.status}'"
        )

    from app.services.commerce import apply_order_tracking

    if data.status == "shipped" or any(
        (data.tracking_number, data.tracking_url, data.carrier)
    ):
        apply_order_tracking(
            order,
            tracking_number=data.tracking_number,
            tracking_url=data.tracking_url,
            carrier=data.carrier,
        )
    await apply_order_status_change(session, order, data.status)
    await session.flush()
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="update",
        resource_type="order",
        resource_id=order.id,
        changes={"status": {"from": old_status, "to": data.status}},
        ip_address=_api_client_ip(request),
    )
    return await serialize_order(session, order)


@router.get("/addons")
async def admin_list_addons(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
):
    """List all discovered addons merged with persisted configuration."""
    from app.services.addons import merge_addon_list

    result = await session.execute(select(AddonConfig))
    stored = {row.addon_id: row for row in result.scalars().all()}
    return merge_addon_list(stored)


@router.put("/addons/{addon_id}")
async def admin_configure_addon(
    request: Request,
    addon_id: str,
    data: dict,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
):
    """Enable/disable and configure an addon."""
    from app.services.addons import persist_addon_config

    row = await persist_addon_config(
        session,
        addon_id,
        data.get("config", {}),
        data.get("is_enabled", False),
    )
    await session.flush()
    await session.refresh(row)
    await log_change(
        session,
        actor_user_id=current_user.id,
        action="update",
        resource_type="addon",
        resource_id=addon_id,
        changes={
            "is_enabled": row.is_enabled,
        },
        ip_address=_api_client_ip(request),
    )
    return {
        "id": row.id,
        "addon_id": row.addon_id,
        "addon_type": row.addon_type,
        "is_enabled": row.is_enabled,
        "config": row.config,
        "updated_at": row.updated_at,
    }


@router.post("/suppliers/{addon_id}/sync", response_model=SupplierCatalogSyncResponse)
async def admin_sync_supplier_catalog(
    request: Request,
    addon_id: str,
    data: SupplierCatalogSyncRequest,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> SupplierCatalogSyncResponse:
    """Import or refresh products from a Printful or Printify catalog."""
    from app.services.supplier_catalog_sync import (
        SupplierCatalogSyncOptions,
        sync_supplier_catalog,
    )

    ip_address = request.client.host if request.client else None
    result = await sync_supplier_catalog(
        session,
        addon_id,
        SupplierCatalogSyncOptions(
            import_status=data.import_status,
            archive_missing=data.archive_missing,
        ),
        actor_user_id=current_user.id,
        ip_address=ip_address,
    )
    return SupplierCatalogSyncResponse(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        archived=result.archived,
        errors=result.errors,
        message=result.summary_message(),
    )


def _serialize_background_job(job) -> BackgroundJobRead:
    from app.services.background_jobs import job_progress_percent

    return BackgroundJobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        payload=job.payload,
        error=job.error,
        percent_complete=job_progress_percent(job),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/jobs/supplier-catalog-sync", response_model=StartSupplierSyncJobResponse)
async def admin_start_supplier_catalog_sync_job(
    request: Request,
    data: SupplierCatalogSyncRequest,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> StartSupplierSyncJobResponse:
    """Start a background job to sync all enabled supplier catalogs."""
    from app.services.background_jobs import (
        SupplierCatalogSyncJobOptions,
        start_supplier_catalog_sync_job,
    )

    ip_address = _api_client_ip(request)
    job = await start_supplier_catalog_sync_job(
        session,
        SupplierCatalogSyncJobOptions(
            import_status=data.import_status,
            archive_missing=data.archive_missing,
            addon_ids=data.addon_ids,
            actor_user_id=current_user.id,
            ip_address=ip_address,
        ),
    )
    await session.commit()
    return StartSupplierSyncJobResponse(
        job_id=job.id,
        status=job.status,
        message="Supplier catalog sync job started",
    )


@router.get("/jobs/{job_id}", response_model=BackgroundJobRead)
async def admin_get_background_job(
    job_id: str,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> BackgroundJobRead:
    """Return background job status and progress."""
    from app.services.background_jobs import get_job

    job = await get_job(session, job_id)
    return _serialize_background_job(job)


@router.post("/jobs/{job_id}/tick", response_model=BackgroundJobRead)
async def admin_tick_background_job(
    job_id: str,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> BackgroundJobRead:
    """Advance a background job by one step."""
    from app.services.background_jobs import tick_supplier_catalog_sync_job

    job = await tick_supplier_catalog_sync_job(session, job_id)
    return _serialize_background_job(job)


class AbandonedCartJobResponse(BaseModel):
    scanned: int
    sent: int
    skipped: int
    message: str


@router.post("/jobs/abandoned-cart", response_model=AbandonedCartJobResponse)
async def admin_run_abandoned_cart_job(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> AbandonedCartJobResponse:
    """Process stale carts and send abandoned-cart reminders (cron entrypoint)."""
    from app.services.abandoned_cart import process_abandoned_carts

    result = await process_abandoned_carts(session)
    return AbandonedCartJobResponse(
        scanned=result.scanned,
        sent=result.sent,
        skipped=result.skipped,
        message=result.summary_message(),
    )


class PendingOrderCleanupResponse(BaseModel):
    scanned: int
    cancelled: int
    skipped: int
    message: str


@router.post("/jobs/pending-orders", response_model=PendingOrderCleanupResponse)
async def admin_run_pending_order_cleanup_job(
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_admin_user),
) -> PendingOrderCleanupResponse:
    """Cancel stale pending orders and restore reserved inventory."""
    from app.services.pending_order_cleanup import process_stale_pending_orders

    result = await process_stale_pending_orders(session)
    return PendingOrderCleanupResponse(
        scanned=result.scanned,
        cancelled=result.cancelled,
        skipped=result.skipped,
        message=result.summary_message(),
    )
