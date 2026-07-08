from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Any,
    AsyncSession,
    Depends,
    File,
    Form,
    Optional,
    RedirectResponse,
    Request,
    UploadFile,
    _common_ctx,
    _render_error,
    _require_csrf,
    _template,
    json,
    require_admin_session,
    select,
    set_flash_cookie,
    settings,
    status,
)

router = APIRouter()

_ADDON_CATEGORY_PAGES: dict[str, dict[str, str]] = {
    "supplier": {
        "nav_section": "suppliers",
        "list_path": "/admin/suppliers",
        "title": "Suppliers",
        "description": "Manage fulfillment and inventory supplier integrations.",
    },
    "payment": {
        "nav_section": "payments",
        "list_path": "/admin/payments",
        "title": "Payments",
        "description": (
            "Manage payment processors for checkout. Only one processor can be enabled at a time."
        ),
    },
    "frontend": {
        "nav_section": "frontends",
        "list_path": "/admin/frontends",
        "title": "Frontends",
        "description": "Manage storefront themes and SPA frontends.",
    },
    "tool": {
        "nav_section": "tools",
        "list_path": "/admin/tools",
        "title": "Tools",
        "description": "Advanced shop utilities: analytics, A/B testing, and other optional integrations.",
    },
    "notification": {
        "nav_section": "notifications",
        "list_path": "/admin/notifications",
        "title": "Notifications",
        "description": (
            "Manage email, SMS, and push notification providers. "
            "Only one provider per channel can be enabled at a time."
        ),
    },
}


def _addon_nav_section(category: str) -> str | None:
    meta = _ADDON_CATEGORY_PAGES.get(category)
    return meta["nav_section"] if meta else None


def _addon_list_path(category: str) -> str:
    meta = _ADDON_CATEGORY_PAGES.get(category)
    return meta["list_path"] if meta else "/admin/suppliers"


async def _admin_addon_category_list(
    request: Request,
    db: AsyncSession | None,
    category: str,
    *,
    extra_context: dict[str, Any] | None = None,
):
    """List addons for a single category."""
    from models.addon_config import AddonConfig
    from app.services.addons import merge_addon_list
    from app.services.supplier_catalog_sync import get_last_sync_times

    page = _ADDON_CATEGORY_PAGES[category]
    stored: dict = {}
    last_sync: dict = {}
    if db is not None:
        try:
            result = await db.execute(select(AddonConfig))
            for row in result.scalars().all():
                stored[row.addon_id] = row
            if category == "supplier":
                last_sync = await get_last_sync_times(db)
        except Exception:
            pass

    addons = [
        a
        for a in merge_addon_list(stored)
        if a["addon_category"] == category
        and not (category == "supplier" and a["addon_id"] == "manual")
    ]

    if category == "supplier":
        from app.addons.registry import addon_registry

        for addon in addons:
            reg = addon_registry.get(addon["addon_id"])
            supports_sync = bool(reg and reg.supports_catalog_sync())
            addon["supports_sync"] = supports_sync
            addon["last_sync_at"] = last_sync.get(addon["addon_id"])
            if supports_sync:
                addon["sync_url"] = f"{addon['configure_url']}#catalog-sync"

    if category == "payment":
        addons.sort(key=lambda a: a.get("addon_name", ""))

    if category == "notification":
        addons.sort(key=lambda a: a.get("addon_name", ""))

    return _template(
        "addons.html",
        **_common_ctx(request, page["title"]),
        addons=addons,
        page_heading=page["title"],
        page_description=page["description"],
        nav_section=page["nav_section"],
        is_suppliers_page=(category == "supplier"),
        is_payments_page=(category == "payment"),
        is_notifications_page=(category == "notification"),
        **(extra_context or {}),
    )


@router.get("/suppliers")
async def admin_suppliers_list(request: Request, db=Depends(require_admin_session)):
    from app.services.background_jobs import get_active_supplier_sync_job, job_progress_percent
    from app.services.supplier_catalog_sync import list_syncable_suppliers

    syncable_count = len(list_syncable_suppliers())
    active_job = None
    if db is not None:
        try:
            job = await get_active_supplier_sync_job(db)
            if job:
                active_job = {
                    "id": job.id,
                    "status": job.status,
                    "percent": job_progress_percent(job),
                }
        except Exception:
            pass

    return await _admin_addon_category_list(
        request,
        db,
        "supplier",
        extra_context={
            "syncable_count": syncable_count,
            "active_sync_job": active_job,
        },
    )


@router.post("/suppliers/sync-all")
async def admin_suppliers_sync_all(
    request: Request,
    import_status: str = Form("draft", max_length=16),
    archive_missing: str = Form(""),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    from app.services.audit import admin_request_meta
    from app.services.background_jobs import (
        SupplierCatalogSyncJobOptions,
        get_active_supplier_sync_job,
        start_supplier_catalog_sync_job,
    )

    _require_csrf(request, csrf_token)

    if db is None:
        return _render_error(request, "Database unavailable")

    try:
        existing = await get_active_supplier_sync_job(db)
        if existing is not None:
            resp = RedirectResponse(url=f"/admin/jobs/{existing.id}", status_code=303)
            set_flash_cookie(resp, "A supplier sync job is already running")
            return resp

        actor_user_id, ip_address = admin_request_meta(request)
        job = await start_supplier_catalog_sync_job(
            db,
            SupplierCatalogSyncJobOptions(
                import_status=import_status,
                archive_missing=(archive_missing == "on"),
                actor_user_id=actor_user_id,
                ip_address=ip_address,
            ),
        )
        await db.commit()
        resp = RedirectResponse(url=f"/admin/jobs/{job.id}", status_code=303)
        set_flash_cookie(resp, "Supplier catalog sync started")
        return resp
    except Exception as exc:
        return _render_error(request, f"Failed to start sync: {exc}")


@router.get("/jobs/{job_id}")
async def admin_job_status(request: Request, job_id: str, db=Depends(require_admin_session)):
    from app.services.background_jobs import (
        addon_display_name,
        get_job,
        job_progress_percent,
        tick_supplier_catalog_sync_job,
    )

    if db is None:
        return _render_error(request, "Database unavailable")

    try:
        job = await get_job(db, job_id)
        if job.status in ("pending", "running"):
            job = await tick_supplier_catalog_sync_job(db, job_id)

        progress = job.progress or {}
        results = progress.get("results") or {}
        addon_ids = progress.get("addon_ids") or (job.payload or {}).get("addon_ids") or []
        result_rows = []
        for addon_id in addon_ids:
            data = results.get(addon_id) or {}
            result_rows.append(
                {
                    "addon_id": addon_id,
                    "addon_name": addon_display_name(addon_id),
                    "message": data.get("message", "Pending"),
                    "errors": data.get("errors") or [],
                    "done": addon_id in results,
                }
            )

        return _template(
            "job_status.html",
            **_common_ctx(request, "Background job"),
            job=job,
            percent=job_progress_percent(job),
            result_rows=result_rows,
            auto_refresh=job.status in ("pending", "running"),
        )
    except Exception as exc:
        return _render_error(request, str(exc), status_code=404)


@router.get("/payments")
async def admin_payments_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "payment")


@router.get("/notifications")
async def admin_notifications_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "notification")


@router.get("/notifications/messages")
async def admin_notification_messages_list(request: Request, db=Depends(require_admin_session)):
    from app.services.notification_events import (
        EVENT_GROUP_ACCOUNT,
        EVENT_GROUP_ORDERS,
        list_events,
    )
    from app.services.notification_templates import get_effective_template

    events = list_events()
    rows: list[dict] = []
    for event in events:
        channels: dict[str, dict] = {}
        for channel in event.channels:
            subject, body, enabled = await get_effective_template(db, event.key, channel)
            channels[channel] = {
                "subject": subject,
                "enabled": enabled,
                "edit_url": f"/admin/notifications/messages/{event.key}/{channel}",
            }
        rows.append(
            {
                "event": event,
                "channels": channels,
            }
        )

    return _template(
        "notification_messages.html",
        **_common_ctx(request, "Notification Messages"),
        nav_section="notifications",
        order_events=[r for r in rows if r["event"].group == EVENT_GROUP_ORDERS],
        account_events=[r for r in rows if r["event"].group == EVENT_GROUP_ACCOUNT],
    )


@router.get("/notifications/messages/{event_key}/{channel}")
async def admin_notification_message_edit(
    request: Request,
    event_key: str,
    channel: str,
    db=Depends(require_admin_session),
):
    from app.services.notification_events import get_event
    from app.services.notification_templates import get_effective_template

    event = get_event(event_key)
    if event is None or channel not in event.channels:
        return _render_error(request, "Unknown notification event or channel", status_code=404)

    subject, body, enabled = await get_effective_template(db, event_key, channel)
    return _template(
        "notification_message_edit.html",
        **_common_ctx(request, f"Edit: {event.label}"),
        nav_section="notifications",
        event=event,
        channel=channel,
        subject=subject,
        body=body,
        is_enabled=enabled,
    )


@router.post("/notifications/messages/{event_key}/{channel}")
async def admin_notification_message_save(
    request: Request,
    event_key: str,
    channel: str,
    subject: str = Form(..., max_length=512),
    body: str = Form(..., max_length=10000),
    is_enabled: str = Form(""),
    action: str = Form("save"),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    from app.admin.session import set_flash_cookie
    from app.services.audit import admin_request_meta, log_change
    from app.services.notification_events import get_event
    from app.services.notification_templates import reset_template, save_template

    _require_csrf(request, csrf_token)
    event = get_event(event_key)
    if event is None or channel not in event.channels:
        return _render_error(request, "Unknown notification event or channel", status_code=404)

    list_url = "/admin/notifications/messages"
    edit_url = f"/admin/notifications/messages/{event_key}/{channel}"
    resource_id = f"{event_key}/{channel}"
    actor_user_id, ip_address = admin_request_meta(request)

    try:
        if action == "reset":
            await reset_template(db, event_key, channel)
            await db.commit()
            await log_change(
                db,
                actor_user_id=actor_user_id,
                action="reset",
                resource_type="notification_template",
                resource_id=resource_id,
                ip_address=ip_address,
                detail="Reset to defaults",
            )
            await db.commit()
            resp = RedirectResponse(url=edit_url, status_code=303)
            set_flash_cookie(resp, "Template reset to defaults")
            return resp

        await save_template(
            db,
            event_key,
            channel,
            subject=subject.strip(),
            body=body,
            is_enabled=(is_enabled == "on"),
        )
        await db.commit()
        body_preview = body[:120] + ("…" if len(body) > 120 else "")
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="update",
            resource_type="notification_template",
            resource_id=resource_id,
            changes={
                "subject": subject.strip(),
                "is_enabled": is_enabled == "on",
            },
            ip_address=ip_address,
            detail=f"Template saved: {body_preview}",
        )
        await db.commit()
        resp = RedirectResponse(url=list_url, status_code=303)
        set_flash_cookie(resp, "Message template saved")
        return resp
    except Exception as exc:
        return _render_error(request, f"Failed to save template: {exc}")


@router.get("/frontends")
async def admin_frontends_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "frontend")


@router.get("/tools")
async def admin_tools_list(request: Request, db=Depends(require_admin_session)):
    return await _admin_addon_category_list(request, db, "tool")


@router.get("/addons")
async def admin_addons_list(request: Request, db=Depends(require_admin_session)):
    """Legacy URL — redirect to suppliers list."""
    return RedirectResponse(url="/admin/suppliers", status_code=302)


def _addon_install_success_message(result) -> str:
    from app.services.addon_install import AddonInstallResult

    assert isinstance(result, AddonInstallResult)
    msg = (
        f"{result.addon_name} (v{result.version}) installed. "
        "Restart the server to load the new addon."
    )
    if result.restart_flag_written and result.restart_flag_path:
        msg += f" A restart flag was written to {result.restart_flag_path}."
    return msg


def _addon_install_error_redirect(request: Request, message: str) -> RedirectResponse:
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    set_flash_cookie(resp, message)
    return resp


@router.post("/addons/install")
async def admin_addon_install_zip(
    request: Request,
    archive: UploadFile = File(...),
    force: str = Form("off", max_length=8),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Install an addon from an uploaded ZIP archive."""
    from app.core.exceptions import ValidationError
    from app.services.addon_install import install_addon_archive, read_limited_stream

    _require_csrf(request, csrf_token)

    if not archive.filename or not archive.filename.lower().endswith(".zip"):
        return _addon_install_error_redirect(request, "Upload must be a .zip file")

    try:
        data = read_limited_stream(archive.file, settings.addon_install_max_bytes)
        result = install_addon_archive(data, force=force == "on")
    except ValidationError as exc:
        return _addon_install_error_redirect(request, exc.message)
    except Exception as exc:
        return _addon_install_error_redirect(request, f"Install failed: {exc}")

    if db is not None:
        from app.services.audit import admin_request_meta, log_change

        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="install",
            resource_type="addon",
            resource_id=result.addon_id,
            changes={
                "addon_id": result.addon_id,
                "category": result.category,
                "version": result.version,
                "source": "zip",
                "force": force == "on",
            },
            ip_address=ip_address,
            detail=f"Installed addon '{result.addon_name}' (v{result.version}) from ZIP",
        )
        await db.commit()

    redirect_url = _addon_list_path(result.category)
    resp = RedirectResponse(url=redirect_url, status_code=302)
    set_flash_cookie(resp, _addon_install_success_message(result))
    return resp


@router.post("/addons/install/url")
async def admin_addon_install_url(
    request: Request,
    url: str = Form(..., max_length=L.ADDON_INSTALL_URL_LEN),
    force: str = Form("off", max_length=8),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Install an addon downloaded from an HTTPS URL."""
    from app.core.exceptions import ValidationError
    from app.services.addon_install import install_addon_from_url

    _require_csrf(request, csrf_token)

    try:
        result = await install_addon_from_url(url.strip(), force=force == "on")
    except ValidationError as exc:
        return _addon_install_error_redirect(request, exc.message)
    except Exception as exc:
        return _addon_install_error_redirect(request, f"Install failed: {exc}")

    if db is not None:
        from app.services.audit import admin_request_meta, log_change

        actor_user_id, ip_address = admin_request_meta(request)
        install_url = url.strip()
        if len(install_url) > 200:
            install_url = install_url[:200] + "…"
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="install",
            resource_type="addon",
            resource_id=result.addon_id,
            changes={
                "addon_id": result.addon_id,
                "category": result.category,
                "version": result.version,
                "source": "url",
                "url": install_url,
                "force": force == "on",
            },
            ip_address=ip_address,
            detail=f"Installed addon '{result.addon_name}' (v{result.version}) from URL",
        )
        await db.commit()

    redirect_url = _addon_list_path(result.category)
    resp = RedirectResponse(url=redirect_url, status_code=302)
    set_flash_cookie(resp, _addon_install_success_message(result))
    return resp


@router.get("/addons/{addon_id}/configure")
async def admin_addon_configure(
    request: Request, addon_id: str, db=Depends(require_admin_session)
):
    """Show generic JSON configuration for addons without dedicated admin UI."""
    from app.addons.registry import addon_registry
    from models.addon_config import AddonConfig

    addon = addon_registry.get(addon_id)
    if addon is None:
        return _render_error(request, f"Unknown addon: {addon_id}", status_code=404)

    if addon.get_admin_routes():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=addon._configure_url(), status_code=302)

    stored_addon: Optional[AddonConfig] = None
    if db is not None:
        try:
            result = await db.execute(
                select(AddonConfig).where(AddonConfig.addon_id == addon_id)
            )
            stored_addon = result.scalar_one_or_none()
        except Exception:
            pass

    config = stored_addon.config if stored_addon else addon_registry.get_config(addon_id)
    config_json = json.dumps(config, indent=2)

    list_path = _addon_list_path(addon.addon_category)
    return _template(
        "addon_config.html",
        **_common_ctx(request, f"Configure: {addon.addon_name}"),
        addon_name=addon.addon_name,
        addon_id=addon_id,
        config_json=config_json,
        is_enabled=stored_addon.is_enabled if stored_addon else addon.is_enabled,
        list_path=list_path,
        list_label=_ADDON_CATEGORY_PAGES.get(addon.addon_category, {}).get(
            "title", "Addons"
        ),
        nav_section=_addon_nav_section(addon.addon_category),
    )


@router.post("/addons/{addon_id}/configure")
async def admin_addon_save_config(
    request: Request,
    addon_id: str,
    is_enabled: str = Form("off", max_length=8),
    config: str = Form("{}", max_length=L.CONFIG_JSON_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Save generic JSON configuration for an addon."""
    from fastapi.responses import RedirectResponse
    from app.addons.registry import addon_registry
    from app.services.addons import persist_addon_config
    from app.services.audit import admin_request_meta, diff_fields, log_change
    from models.addon_config import AddonConfig

    _require_csrf(request, csrf_token)

    if addon_registry.get(addon_id) is None:
        return _render_error(request, f"Unknown addon: {addon_id}", status_code=404)

    try:
        config_data = json.loads(config)
    except (json.JSONDecodeError, TypeError):
        return _render_error(request, "Invalid JSON in config")

    enabled = is_enabled == "on"

    if not db:
        return _render_error(request, "Database unavailable")

    try:
        addon = addon_registry.get(addon_id)
        stored_result = await db.execute(
            select(AddonConfig).where(AddonConfig.addon_id == addon_id)
        )
        stored_addon = stored_result.scalar_one_or_none()
        before_enabled = stored_addon.is_enabled if stored_addon else False
        before_config = (
            stored_addon.config
            if stored_addon and isinstance(stored_addon.config, dict)
            else addon_registry.get_config(addon_id) or {}
        )

        await persist_addon_config(db, addon_id, config_data, enabled)
        await db.commit()

        changes: dict[str, Any] = {}
        if before_enabled != enabled:
            changes["is_enabled"] = {"from": before_enabled, "to": enabled}
        config_changes = diff_fields(
            before_config if isinstance(before_config, dict) else {},
            config_data if isinstance(config_data, dict) else {},
        )
        if config_changes:
            changes["config"] = config_changes

        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="configure",
            resource_type="addon",
            resource_id=addon_id,
            changes=changes or None,
            ip_address=ip_address,
            detail=f"Configured addon '{addon.addon_name if addon else addon_id}'",
        )
        await db.commit()

        list_url = _addon_list_path(addon.addon_category) if addon else "/admin/suppliers"
        resp = RedirectResponse(url=list_url, status_code=302)
        set_flash_cookie(
            resp,
            f"{addon.addon_name if addon else addon_id} configuration saved",
        )
        return resp

    except Exception as exc:
        return _render_error(request, f"Failed to save config: {exc}")


