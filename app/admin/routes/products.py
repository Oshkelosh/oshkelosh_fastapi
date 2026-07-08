from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    File,
    Form,
    Optional,
    Query,
    RedirectResponse,
    Request,
    UploadFile,
    _common_ctx,
    _render_error,
    _render_product_form,
    _require_csrf,
    _template,
    col,
    func,
    json,
    mark_instance_dirty,
    require_admin_session,
    select,
    set_flash_cookie,
    status,
)

router = APIRouter()


def _parse_product_options(raw: str) -> dict[str, str]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def _supplier_variant_fields(
    supplier_value: str,
    supplier_product_id: str,
    supplier_variant_id: str,
) -> tuple[str | None, str | None, str | None]:
    from app.services.suppliers import _addon_id_from_supplier_value

    if not supplier_value.strip():
        return None, None, None
    addon_id = _addon_id_from_supplier_value(supplier_value)
    product_ref = supplier_product_id.strip() or None
    variant_ref = supplier_variant_id.strip() or None
    if addon_id == "manual" and supplier_value.startswith("manual:"):
        slug = supplier_value.removeprefix("manual:").strip()
        if slug:
            variant_ref = slug
    return addon_id, product_ref, variant_ref


async def _apply_manual_variant_updates(
    request: Request,
    db,
    product,
    *,
    synced: bool,
) -> None:
    """Apply variant field updates from the product form for manual products."""
    from app.services.product_variants import list_variants_for_product, refresh_product_listing_cache

    if synced:
        return
    form = await request.form()
    variants = await list_variants_for_product(db, product.id)
    for variant in variants:
        prefix = f"variant_{variant.id}_"
        title = form.get(f"{prefix}title")
        if title is not None:
            variant.title = str(title).strip() or variant.title
        price = form.get(f"{prefix}price_cents")
        if price is not None and str(price).strip():
            variant.price_cents = max(0, int(price))
        inventory = form.get(f"{prefix}inventory_quantity")
        if inventory is not None and str(inventory).strip():
            variant.inventory_quantity = max(0, int(inventory))
        compare = form.get(f"{prefix}compare_at_price_cents")
        if compare is not None:
            compare_text = str(compare).strip()
            variant.compare_at_price_cents = int(compare_text) if compare_text else None
        status = form.get(f"{prefix}status")
        if status is not None and str(status).strip():
            variant.status = str(status).strip()
        db.add(variant)
    refresh_product_listing_cache(product, variants)
    mark_instance_dirty(db, product)


@router.get("/products")
async def admin_products_list(
    request: Request,
    page: int = Query(1, ge=1),
    db=Depends(require_admin_session),
):
    """List products with pagination."""
    from app.services.product_images import primary_image_urls_for_products
    from app.services.product_variants import get_variants_for_products
    from app.services.suppliers import variant_supplier_label
    from app.services.product_slugs import ensure_product_slug, sku_exists, slug_exists
    from models.product import Product
    from models.category import Category

    PAGE_SIZE = 20
    offset = (page - 1) * PAGE_SIZE

    stmt = (
        select(Product)
        .order_by(col(Product.created_at).desc())
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    count_stmt = select(func.count(Product.id))

    total = 0
    items = []
    supplier_labels: dict[int, str] = {}
    primary_images: dict[int, str] = {}

    if db is not None:
        try:
            count_result = await db.execute(count_stmt)
            total = count_result.scalar() or 0

            result = await db.execute(stmt)
            items = result.scalars().all()
            product_ids = [product.id for product in items if product.id is not None]
            variants_by_product = await get_variants_for_products(db, product_ids)
            supplier_labels = {}
            for product in items:
                if product.id is None:
                    continue
                variants = variants_by_product.get(product.id, [])
                label = ""
                for variant in variants:
                    label = variant_supplier_label(variant)
                    if label:
                        break
                supplier_labels[product.id] = label
            primary_images = await primary_image_urls_for_products(db, product_ids)
        except Exception:
            pass

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Gather all categories for the dropdown (used on the form page too)
    categories = []
    if db is not None:
        try:
            cat_result = await db.execute(select(Category).order_by(col(Category.sort_order).asc()))
            categories = cat_result.scalars().all()
        except Exception:
            pass

    return _template(
        "products.html",
        **_common_ctx(request, "Products"),
        items=items,
        supplier_labels=supplier_labels,
        primary_images=primary_images,
        page=page,
        total=total,
        total_pages=total_pages,
        page_size=PAGE_SIZE,
        categories=categories,
    )


@router.get("/products/new")
async def admin_product_new(request: Request, db=Depends(require_admin_session)):
    """Show the create-product form."""
    from app.services.suppliers import supplier_form_values

    supplier_value, supplier_product_id, supplier_variant_id = supplier_form_values(None)

    return await _render_product_form(
        request,
        db,
        title="New Product",
        product=None,
        action_url="/admin/products",
        supplier_value=supplier_value,
        supplier_product_id=supplier_product_id,
        supplier_variant_id=supplier_variant_id,
        other_tags_json="[]",
        product_options_json="{}",
        product_variants=[],
    )


@router.post("/products")
async def admin_product_create(
    request: Request,
    name: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    slug: str = Form("", max_length=L.NAME_LEN),
    meta_title: str = Form("", max_length=L.NAME_LEN),
    meta_description: str = Form("", max_length=L.TEXT_LEN),
    price_cents: int = Form(ge=0, alias="price_cents"),
    compare_at_price_cents: Optional[int] = Form(None, ge=0, alias="compare_at_price_cents"),
    sku: Optional[str] = Form(None, max_length=L.SKU_LEN),
    inventory_quantity: int = Form(0, ge=0),
    status: str = Form("draft", max_length=32),
    category_id: Optional[int] = Form(None),
    supplier_value: str = Form("", max_length=100),
    supplier_product_id: str = Form("", max_length=255),
    supplier_variant_id: str = Form("", max_length=255),
    tags: str = Form("[]", max_length=L.TAGS_JSON_LEN),
    product_options: str = Form("{}", max_length=L.TAGS_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Create a new product."""
    from types import SimpleNamespace

    from fastapi.responses import RedirectResponse
    from app.services.categories import resolve_category_id
    from app.services.product_defaults import apply_product_creation_defaults
    from app.services.product_variants import create_default_variant
    from app.services.site_settings import get_site_settings
    from app.services.suppliers import validate_supplier_form
    from app.services.product_slugs import sku_exists, slug_exists
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not (sku and sku.strip()):
        draft = SimpleNamespace(
            name=name,
            description=description or "",
            price_cents=price_cents,
            compare_at_price_cents=compare_at_price_cents,
            sku=sku,
            inventory_quantity=inventory_quantity,
            status=status,
            category_id=category_id,
        )
        return await _render_product_form(
            request,
            db,
            title="New Product",
            product=draft,
            action_url="/admin/products",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash="SKU is required when creating a product.",
            flash_type="error",
        )

    supplier_error = validate_supplier_form(
        supplier_value, supplier_product_id, supplier_variant_id
    )
    if supplier_error:
        draft = SimpleNamespace(
            name=name,
            description=description or "",
            price_cents=price_cents,
            compare_at_price_cents=compare_at_price_cents,
            sku=sku,
            inventory_quantity=inventory_quantity,
            status=status,
            category_id=category_id,
        )
        return await _render_product_form(
            request,
            db,
            title="New Product",
            product=draft,
            action_url="/admin/products",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash=supplier_error,
            flash_type="error",
        )

    try:
        parsed_tags = json.loads(tags) if tags else []
    except (json.JSONDecodeError, TypeError):
        parsed_tags = []

    parsed_tags = [
        t
        for t in parsed_tags
        if not (isinstance(t, dict) and t.get("supplier_addon_id"))
    ]
    parsed_options = _parse_product_options(product_options)

    if not db:
        return _render_error(request, "Database unavailable")

    if slug and await slug_exists(db, slug):
        return await _render_product_form(
            request,
            db,
            title="New Product",
            product=SimpleNamespace(
                name=name,
                description=description or "",
                slug=slug,
                meta_title=meta_title,
                meta_description=meta_description,
                price_cents=price_cents,
                compare_at_price_cents=compare_at_price_cents,
                sku=sku,
                inventory_quantity=inventory_quantity,
                status=status,
                category_id=category_id,
            ),
            action_url="/admin/products",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash=f"Product with slug '{slug}' already exists",
            flash_type="error",
        )

    if sku and await sku_exists(db, sku):
        return await _render_product_form(
            request,
            db,
            title="New Product",
            product=SimpleNamespace(
                name=name,
                description=description or "",
                slug=slug,
                meta_title=meta_title,
                meta_description=meta_description,
                price_cents=price_cents,
                compare_at_price_cents=compare_at_price_cents,
                sku=sku,
                inventory_quantity=inventory_quantity,
                status=status,
                category_id=category_id,
            ),
            action_url="/admin/products",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash=f"Product with SKU '{sku}' already exists",
            flash_type="error",
        )

    resolved_category_id = await resolve_category_id(db, category_id)

    product = Product(
        name=name,
        description=description or None,
        meta_title=meta_title or None,
        meta_description=meta_description or None,
        price_cents=price_cents,
        compare_at_price_cents=compare_at_price_cents,
        sku=sku.strip(),
        inventory_quantity=inventory_quantity,
        status=status,
        category_id=resolved_category_id,
        tags=parsed_tags,
        options=parsed_options,
        created_by=request.state.admin_user.id,
    )
    db.add(product)
    await db.flush()
    addon_id, supplier_product_ref, supplier_variant_ref = _supplier_variant_fields(
        supplier_value, supplier_product_id, supplier_variant_id
    )
    await create_default_variant(
        db,
        product,
        price_cents=price_cents,
        inventory_quantity=inventory_quantity,
        sku=sku.strip() if sku else None,
        supplier_addon_id=addon_id,
        supplier_product_id=supplier_product_ref,
        supplier_variant_id=supplier_variant_ref,
    )
    if db:
        site_settings = await get_site_settings(db)
        store_name = site_settings.store_name or "Store"
        await apply_product_creation_defaults(
            db,
            product,
            store_name=store_name,
            preferred_slug=slug or None,
        )
        mark_instance_dirty(db, product)

    await db.commit()
    await db.refresh(product)

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="create",
        resource_type="product",
        resource_id=product.id,
        changes={
            "name": product.name,
            "status": product.status,
            "price_cents": product.price_cents,
            "sku": product.sku,
        },
        ip_address=ip_address,
        detail=f"Created product '{product.name}'",
    )
    await db.commit()

    resp = RedirectResponse(url=f"/admin/products/{product.id}", status_code=302)
    set_flash_cookie(resp, f"Product '{product.name}' created — add images below")
    return resp


@router.get("/products/{product_id}")
async def admin_product_edit(request: Request, product_id: int, db=Depends(require_admin_session)):
    """Show the edit-product form."""
    from app.services.product_defaults import product_is_sync_imported
    from app.services.product_images import list_product_images
    from app.services.product_variants import list_variants_for_product
    from app.services.suppliers import non_supplier_tags, supplier_form_values, variant_supplier_label
    from models.product import Product

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    product_variants = await list_variants_for_product(db, product_id)
    default_variant = product_variants[0] if product_variants else None
    supplier_value, supplier_product_id, supplier_variant_id = supplier_form_values(
        product, default_variant
    )
    product_images = await list_product_images(db, product_id)

    return await _render_product_form(
        request,
        db,
        title=f"Edit: {product.name}",
        product=product,
        action_url=f"/admin/products/{product_id}",
        supplier_value=supplier_value,
        supplier_product_id=supplier_product_id,
        supplier_variant_id=supplier_variant_id,
        other_tags_json=json.dumps(non_supplier_tags(product.tags)),
        product_options_json=json.dumps(product.options or {}),
        product_is_sync_imported=product_is_sync_imported(product),
        supplier_label=variant_supplier_label(default_variant),
        product_images=product_images,
        product_variants=product_variants,
    )


@router.post("/products/{product_id}")
async def admin_product_update(
    request: Request,
    product_id: int,
    name: str = Form(..., max_length=L.NAME_LEN),
    description: str = Form("", max_length=L.TEXT_LEN),
    slug: str = Form("", max_length=L.NAME_LEN),
    meta_title: str = Form("", max_length=L.NAME_LEN),
    meta_description: str = Form("", max_length=L.TEXT_LEN),
    price_cents: int = Form(ge=0, alias="price_cents"),
    compare_at_price_cents: Optional[int] = Form(None, ge=0, alias="compare_at_price_cents"),
    sku: Optional[str] = Form(None, max_length=L.SKU_LEN),
    inventory_quantity: int = Form(0, ge=0),
    status: str = Form("draft", max_length=32),
    category_id: Optional[int] = Form(None),
    supplier_value: str = Form("", max_length=100),
    supplier_product_id: str = Form("", max_length=255),
    supplier_variant_id: str = Form("", max_length=255),
    tags: str = Form("[]", max_length=L.TAGS_JSON_LEN),
    product_options: str = Form("{}", max_length=L.TAGS_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Update an existing product."""
    from fastapi.responses import RedirectResponse
    from app.services.categories import resolve_category_id
    from app.services.product_defaults import enforce_immutable_product_fields, product_is_sync_imported
    from app.services.product_slugs import ensure_product_slug, slug_exists
    from app.services.product_variants import list_variants_for_product
    from app.services.suppliers import (
        non_supplier_tags,
        supplier_form_values,
        variant_supplier_label,
    )
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    from app.services.audit import admin_request_meta, diff_fields, log_change

    _PRODUCT_AUDIT_KEYS = {
        "name",
        "slug",
        "status",
        "price_cents",
        "compare_at_price_cents",
        "sku",
        "inventory_quantity",
        "category_id",
    }
    product_before = {key: getattr(product, key) for key in _PRODUCT_AUDIT_KEYS}
    product_variants = await list_variants_for_product(db, product_id)
    default_variant = product_variants[0] if product_variants else None
    synced = product_is_sync_imported(product)

    immutable_error = enforce_immutable_product_fields(
        product,
        default_variant,
        sku=sku,
        supplier_value=supplier_value,
        supplier_product_id=supplier_product_id,
        supplier_variant_id=supplier_variant_id,
        category_id=category_id,
    )
    if immutable_error:
        return await _render_product_form(
            request,
            db,
            title=f"Edit: {name}",
            product=product,
            action_url=f"/admin/products/{product_id}",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash=immutable_error,
            flash_type="error",
            product_is_sync_imported=synced,
            supplier_label=variant_supplier_label(default_variant),
            product_variants=product_variants,
            product_options_json=product_options,
        )

    try:
        parsed_tags = json.loads(tags) if tags else []
    except (json.JSONDecodeError, TypeError):
        parsed_tags = []

    parsed_tags = [
        t
        for t in parsed_tags
        if not (isinstance(t, dict) and t.get("supplier_addon_id"))
    ]
    sync_markers = [t for t in (product.tags or []) if isinstance(t, dict) and t.get("supplier_sync")]
    parsed_tags.extend(sync_markers)
    parsed_options = _parse_product_options(product_options)

    if slug and await slug_exists(db, slug, exclude_id=product_id):
        product.name = name
        product.description = description or None
        product.meta_title = meta_title or None
        product.meta_description = meta_description or None
        product.price_cents = price_cents
        product.compare_at_price_cents = compare_at_price_cents
        product.inventory_quantity = inventory_quantity
        product.status = status
        return await _render_product_form(
            request,
            db,
            title=f"Edit: {name}",
            product=product,
            action_url=f"/admin/products/{product_id}",
            supplier_value=supplier_value,
            supplier_product_id=supplier_product_id,
            supplier_variant_id=supplier_variant_id,
            other_tags_json=tags,
            flash=f"Product with slug '{slug}' already exists",
            flash_type="error",
            product_is_sync_imported=synced,
            supplier_label=variant_supplier_label(default_variant),
            product_variants=product_variants,
            product_options_json=product_options,
        )

    product.name = name
    product.description = description or None
    product.meta_title = meta_title or None
    product.meta_description = meta_description or None
    product.status = status
    product.options = parsed_options
    if not synced:
        product.category_id = await resolve_category_id(db, category_id)
    product.tags = parsed_tags
    product.updated_by = request.state.admin_user.id
    await _apply_manual_variant_updates(request, db, product, synced=synced)
    slug_preferred = slug.strip() if slug and slug.strip() else None
    if slug_preferred:
        await ensure_product_slug(db, product, preferred=slug_preferred)
    mark_instance_dirty(db, product)

    await db.commit()
    await db.refresh(product)

    product_after = {key: getattr(product, key) for key in _PRODUCT_AUDIT_KEYS}
    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="product",
        resource_id=product.id,
        changes=diff_fields(product_before, product_after, keys=_PRODUCT_AUDIT_KEYS),
        ip_address=ip_address,
        detail=f"Updated product '{product.name}'",
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/products", status_code=302)
    set_flash_cookie(resp, f"Product '{product.name}' updated")
    return resp


@router.post("/products/{product_id}/images")
async def admin_product_image_upload(
    request: Request,
    product_id: int,
    file: UploadFile = File(...),
    alt_text: str = Form("", max_length=500),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Upload an image for a product."""
    from app.core.exceptions import ValidationError
    from app.services.product_images import read_upload_file, upload_product_image
    from app.storage import get_storage
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    product = await db.get(Product, product_id)
    if product is None:
        return _render_error(request, "Product not found", status_code=404)

    try:
        content, content_type = await read_upload_file(file)
        storage = get_storage()
        await upload_product_image(
            db,
            product,
            content,
            content_type,
            storage=storage,
            alt_text=alt_text or product.name,
        )
        await db.commit()
    except ValidationError as exc:
        resp = RedirectResponse(url=f"/admin/products/{product_id}", status_code=302)
        set_flash_cookie(resp, exc.message)
        return resp

    resp = RedirectResponse(url=f"/admin/products/{product_id}", status_code=302)
    set_flash_cookie(resp, "Image uploaded")
    return resp


@router.post("/products/{product_id}/images/{image_id}/delete")
async def admin_product_image_delete(
    request: Request,
    product_id: int,
    image_id: int,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Delete a product image."""
    from app.services.product_images import delete_product_image
    from app.storage import get_storage
    from models.product_image import ProductImage

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    image = await db.get(ProductImage, image_id)
    if image is None or image.product_id != product_id:
        return _render_error(request, "Image not found", status_code=404)

    storage = get_storage()
    await delete_product_image(db, image, storage=storage)
    await db.commit()

    resp = RedirectResponse(url=f"/admin/products/{product_id}", status_code=302)
    set_flash_cookie(resp, "Image deleted")
    return resp


@router.post("/products/{product_id}/delete")
async def admin_product_delete(
    request: Request,
    product_id: int,
    csrf_token: str = Form(...),
    db=Depends(require_admin_session),
):
    """Delete a product."""
    from fastapi.responses import RedirectResponse
    from models.product import Product

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        result = await db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
    except Exception:
        return _render_error(request, "Database error")

    if not product:
        return _render_error(request, "Product not found", status_code=404)

    from app.services.product_slugs import product_has_order_items

    if await product_has_order_items(db, product_id):
        resp = RedirectResponse(url="/admin/products", status_code=302)
        set_flash_cookie(
            resp,
            f"Cannot delete '{product.name}': it appears on existing orders",
        )
        return resp

    product_name = product.name
    await db.delete(product)
    await db.commit()

    from app.services.audit import admin_request_meta, log_change

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="delete",
        resource_type="product",
        resource_id=product_id,
        ip_address=ip_address,
        detail=f"Deleted product '{product_name}'",
    )
    await db.commit()

    resp = RedirectResponse(url="/admin/products", status_code=302)
    set_flash_cookie(resp, f"Product '{product_name}' deleted")
    return resp


