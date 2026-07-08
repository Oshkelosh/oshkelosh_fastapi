from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    File,
    Form,
    RedirectResponse,
    Request,
    UploadFile,
    _common_ctx,
    _render_error,
    _require_csrf,
    _template,
    json,
    require_admin_session,
    set_flash_cookie,
    settings,
)

router = APIRouter()


@router.get("/settings")
async def admin_site_settings(request: Request, db=Depends(require_admin_session)):
    """Edit site-wide branding and contact settings."""
    from app.services.site_settings import get_site_settings

    site = await get_site_settings(db)
    return _template(
        "site_settings.html",
        **_common_ctx(request, "Site Settings"),
        site=site,
        tax_zones_json=json.dumps(site.tax_zones_json or [], indent=2),
        shipping_zones_json=json.dumps(site.shipping_zones_json or [], indent=2),
    )


@router.post("/settings")
async def admin_site_settings_save(
    request: Request,
    store_name: str = Form(..., max_length=L.NAME_LEN),
    primary_color: str = Form("#2563eb", max_length=L.COLOR_LEN),
    secondary_color: str = Form("#64748b", max_length=L.COLOR_LEN),
    font_family: str = Form("system-ui, sans-serif", max_length=L.NAME_LEN),
    support_email: str = Form("", max_length=L.EMAIL_LEN),
    meta_description: str = Form("", max_length=L.TEXT_LEN),
    tax_enabled: str = Form(""),
    tax_inclusive: str = Form(""),
    tax_rate_bps: int = Form(800),
    tax_zones_json: str = Form("[]", max_length=L.TEXT_LEN),
    shipping_mode: str = Form("flat", max_length=32),
    shipping_flat_cents: int = Form(500),
    shipping_free_threshold_cents: str = Form(""),
    shipping_zones_json: str = Form("[]", max_length=L.TEXT_LEN),
    abandoned_cart_enabled: str = Form(""),
    abandoned_cart_delay_hours: int = Form(24),
    abandoned_cart_max_reminders: int = Form(1),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Save site-wide settings."""
    from app.services.audit import admin_request_meta, diff_fields, log_change
    from app.services.site_settings import get_site_settings, site_settings_to_dict, update_site_settings

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        before = site_settings_to_dict(await get_site_settings(db))
        await update_site_settings(
            db,
            {
                "store_name": store_name,
                "primary_color": primary_color,
                "secondary_color": secondary_color,
                "font_family": font_family,
                "support_email": support_email,
                "meta_description": meta_description,
                "tax_enabled": tax_enabled,
                "tax_inclusive": tax_inclusive,
                "tax_rate_bps": tax_rate_bps,
                "tax_zones_json": tax_zones_json,
                "shipping_mode": shipping_mode,
                "shipping_flat_cents": shipping_flat_cents,
                "shipping_free_threshold_cents": shipping_free_threshold_cents,
                "shipping_zones_json": shipping_zones_json,
                "abandoned_cart_enabled": abandoned_cart_enabled,
                "abandoned_cart_delay_hours": abandoned_cart_delay_hours,
                "abandoned_cart_max_reminders": abandoned_cart_max_reminders,
            },
        )
        await db.commit()
        after = site_settings_to_dict(await get_site_settings(db))

        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="update",
            resource_type="site_settings",
            resource_id=1,
            changes=diff_fields(before, after, keys=set(before.keys())),
            ip_address=ip_address,
            detail="Site settings updated",
        )
        await db.commit()
        request.state.site_settings = await get_site_settings(db)
        resp = RedirectResponse(url=f"{settings.admin_prefix}/settings", status_code=302)
        set_flash_cookie(resp, "Site settings saved")
        return resp
    except Exception as exc:
        return _render_error(request, f"Failed to save settings: {exc}")


async def _save_branding_asset(
    request: Request,
    db,
    *,
    kind: str,
    file: UploadFile,
    csrf_token: str,
    field_name: str,
    label: str,
) -> RedirectResponse:
    from app.core.exceptions import ValidationError
    from app.services.audit import admin_request_meta, diff_fields, log_change
    from app.services.branding_assets import (
        delete_branding_asset_if_managed,
        upload_branding_asset,
    )
    from app.services.product_images import read_upload_file
    from app.services.site_settings import get_site_settings, site_settings_to_dict, update_site_settings
    from app.storage import get_storage

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        content, content_type = await read_upload_file(file)
        storage = get_storage()
        before = site_settings_to_dict(await get_site_settings(db))
        prior_url = getattr(await get_site_settings(db), field_name)
        await delete_branding_asset_if_managed(prior_url, storage=storage)
        public_url = await upload_branding_asset(kind, content, content_type, storage=storage)
        await update_site_settings(db, {field_name: public_url})
        await db.commit()
        after = site_settings_to_dict(await get_site_settings(db))

        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="update",
            resource_type="site_settings",
            resource_id=1,
            changes=diff_fields(before, after, keys={field_name}),
            ip_address=ip_address,
            detail=f"{label} uploaded",
        )
        await db.commit()
        request.state.site_settings = await get_site_settings(db)
        resp = RedirectResponse(url=f"{settings.admin_prefix}/settings", status_code=302)
        set_flash_cookie(resp, f"{label} uploaded")
        return resp
    except ValidationError as exc:
        resp = RedirectResponse(url=f"{settings.admin_prefix}/settings", status_code=302)
        set_flash_cookie(resp, exc.message)
        return resp


async def _clear_branding_asset(
    request: Request,
    db,
    *,
    csrf_token: str,
    field_name: str,
    label: str,
) -> RedirectResponse:
    from app.services.audit import admin_request_meta, diff_fields, log_change
    from app.services.branding_assets import delete_branding_asset_if_managed
    from app.services.site_settings import get_site_settings, site_settings_to_dict, update_site_settings
    from app.storage import get_storage

    _require_csrf(request, csrf_token)

    if not db:
        return _render_error(request, "Database unavailable")

    site = await get_site_settings(db)
    before = site_settings_to_dict(site)
    prior_url = getattr(site, field_name)
    storage = get_storage()
    await delete_branding_asset_if_managed(prior_url, storage=storage)
    await update_site_settings(db, {field_name: None})
    await db.commit()
    after = site_settings_to_dict(await get_site_settings(db))

    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="site_settings",
        resource_id=1,
        changes=diff_fields(before, after, keys={field_name}),
        ip_address=ip_address,
        detail=f"{label} removed",
    )
    await db.commit()
    request.state.site_settings = await get_site_settings(db)
    resp = RedirectResponse(url=f"{settings.admin_prefix}/settings", status_code=302)
    set_flash_cookie(resp, f"{label} removed")
    return resp


@router.post("/settings/logo")
async def admin_site_logo_upload(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Upload the site logo."""
    return await _save_branding_asset(
        request,
        db,
        kind="logo",
        file=file,
        csrf_token=csrf_token,
        field_name="logo_url",
        label="Logo",
    )


@router.post("/settings/favicon")
async def admin_site_favicon_upload(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Upload the site favicon."""
    return await _save_branding_asset(
        request,
        db,
        kind="favicon",
        file=file,
        csrf_token=csrf_token,
        field_name="favicon_url",
        label="Favicon",
    )


@router.post("/settings/logo/clear")
async def admin_site_logo_clear(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Remove the site logo."""
    return await _clear_branding_asset(
        request,
        db,
        csrf_token=csrf_token,
        field_name="logo_url",
        label="Logo",
    )


@router.post("/settings/favicon/clear")
async def admin_site_favicon_clear(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Remove the site favicon."""
    return await _clear_branding_asset(
        request,
        db,
        csrf_token=csrf_token,
        field_name="favicon_url",
        label="Favicon",
    )
