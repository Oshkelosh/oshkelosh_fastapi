"""Shared admin and thin API route factories for payment addons."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.addons.admin_helpers import (
    make_addon_jinja_env,
    redact_secret_values,
    render_addon_admin_page,
    save_addon_from_form,
)
from app.addons.log import exception
from app.addons.registry import addon_registry
from app.admin.routes import require_admin_session
from app.config import settings
from app.db.connection import get_session
from app.services.payment_webhooks import process_payment_webhook
from app.services.site_settings import resolve_public_site_url


def build_payment_routers(
    addon_id: str,
    *,
    template_name: str,
    page_title: str,
    secret_keys: tuple[str, ...] = (),
    parse_config_form: Callable[[Any], tuple[dict[str, Any], bool]],
    signature_header: str | None = None,
) -> tuple[APIRouter, APIRouter, Any]:
    """Return (admin_router, api_router, jinja_env) for a payment addon."""
    templates_dir = Path(__file__).resolve().parent / addon_id / "templates"
    jinja_env = make_addon_jinja_env(templates_dir)
    configure_url = f"/admin/payments/{addon_id}"
    sig_header = signature_header or "signature"

    admin_router = APIRouter()
    api_router = APIRouter()

    def _masked_config(addon: Any) -> dict[str, Any]:
        if addon and hasattr(addon, "_config") and addon._config:
            return redact_secret_values(dict(addon._config), *secret_keys)
        return {}

    def _webhook_context(request: Request) -> dict[str, str]:
        public_app_url = resolve_public_site_url(request=request)
        return {
            "public_app_url": public_app_url,
            "webhook_url": (
                f"{public_app_url}{settings.api_v1_prefix}/payments/{addon_id}/webhook"
            ),
        }

    @admin_router.get("")
    async def config_page(request: Request, db=Depends(require_admin_session)):
        addon = addon_registry.get(addon_id)
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                template_name,
                page_title,
                addon=addon,
                config=_masked_config(addon),
                **_webhook_context(request),
            ),
        )

    @admin_router.get("/", include_in_schema=False)
    async def config_trailing_slash_redirect():
        return RedirectResponse(url=configure_url, status_code=307)

    @admin_router.post("/save")
    async def save_config(request: Request, db=Depends(require_admin_session)):
        from app.addons.admin_helpers import require_addon_csrf

        try:
            form = await request.form()
            require_addon_csrf(request, str(form.get("csrf_token", "")))
            config, enabled = parse_config_form(form)
            return await save_addon_from_form(
                db,
                addon_id,
                config,
                enabled=enabled,
                redirect_url=configure_url,
                flash_message=f"{page_title} saved",
            )
        except Exception as exc:
            addon = addon_registry.get(addon_id)
            return HTMLResponse(
                content=render_addon_admin_page(
                    jinja_env,
                    request,
                    template_name,
                    page_title,
                    flash=f"Error saving config: {exc}",
                    flash_type="error",
                    addon=addon,
                    config=_masked_config(addon),
                    **_webhook_context(request),
                ),
            )

    @api_router.post("/webhook")
    async def addon_webhook(request: Request, session=Depends(get_session)):
        body = await request.body()
        header_name = signature_header or sig_header
        signature = request.headers.get(header_name, "")

        addon = addon_registry.get(addon_id)
        if addon is None:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": f"{addon_id} addon is not registered"},
            )

        if not getattr(addon, "is_enabled", False):
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": f"{addon_id} addon is not enabled"},
            )

        # Fail closed: a payment addon must positively verify the webhook before
        # core marks any order paid. The base PaymentAddon.verify_webhook rejects
        # by default, so a missing/incorrect override rejects rather than trusts.
        try:
            ok = await addon.verify_webhook(headers=request.headers, body=body)
        except Exception:
            exception(page_title, "webhook verification failed")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Webhook verification failed"},
            )
        if not ok:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid webhook signature"},
            )

        try:
            payload = json.loads(body.decode("utf-8"))
            event_id = addon.webhook_event_id(payload)
            if not event_id:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"error": "Missing webhook event id"},
                )

            result = await process_payment_webhook(
                session,
                addon,
                payload=payload,
                signature=signature,
                event_id=event_id,
            )
            return JSONResponse(content=result)
        except Exception:
            exception(page_title, "webhook processing failed")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Webhook processing failed"},
            )

    return admin_router, api_router, jinja_env
