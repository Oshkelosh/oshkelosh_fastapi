"""SSO tool addon routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError
from pydantic import BaseModel, Field

from app.addons.log import warning
from app.addons.admin_helpers import make_addon_jinja_env, render_addon_admin_page, save_addon_from_form
from app.addons.registry import addon_registry
from app.addons.tools.sso.addon import SsoToolAddon
from app.addons.tools.sso.service import (
    api_base_url,
    build_authorize_url,
    build_public_providers,
    build_spa_callback_redirect,
    callback_url,
    decode_sso_exchange_token,
    handle_oauth_callback,
    public_app_url,
    create_sso_exchange_token,
)
from app.admin.routes import require_admin_session
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.rate_limit import limiter
from app.db.connection import get_session
from app.services.auth_tokens import build_token_response
from models.user import User

_CONFIGURE_URL = "/admin/tools/sso"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

jinja_env = make_addon_jinja_env(_TEMPLATES_DIR)

api_router = APIRouter()
admin_router = APIRouter()


def _get_sso_addon() -> SsoToolAddon:
    addon = addon_registry.get("sso")
    if addon is None or not isinstance(addon, SsoToolAddon) or not addon.is_enabled:
        raise ValidationError(message="SSO is not enabled")
    return addon


class SsoExchangeRequest(BaseModel):
    exchange_token: str = Field(min_length=16, max_length=2048)


@api_router.get("/providers")
async def list_sso_providers():
    addon = addon_registry.get("sso")
    if addon is None or not isinstance(addon, SsoToolAddon) or not addon.is_enabled:
        return {"providers": []}
    return {"providers": build_public_providers(addon.providers)}


@api_router.get("/{provider_id}/authorize")
async def sso_authorize(
    provider_id: str,
    redirect: str = Query("/", max_length=512),
):
    addon = _get_sso_addon()
    # Require a single-slash relative path: "//host" is protocol-relative and
    # "/\host" is treated as "//host" by browsers — both are open redirects.
    if (
        not redirect.startswith("/")
        or redirect.startswith("//")
        or "\\" in redirect
    ):
        redirect = "/"
    safe_redirect = redirect
    if provider_id not in addon.providers:
        warning("SSO", "Authorize requested for unknown provider={}", provider_id)
    url = build_authorize_url(addon.providers, provider_id, safe_redirect)
    return RedirectResponse(url=url, status_code=302)


@api_router.get("/{provider_id}/callback")
async def sso_callback(
    provider_id: str,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=16),
    session=Depends(get_session),
):
    addon = _get_sso_addon()
    try:
        user_id, redirect_after = await handle_oauth_callback(
            session,
            addon.providers,
            provider_id,
            code,
            state,
        )
    except ValidationError as exc:
        warning("SSO", "OAuth callback validation failed for provider={}: {}", provider_id, exc)
        return RedirectResponse(
            url=f"{public_app_url()}/login?error=sso_failed",
            status_code=302,
        )
    except AuthenticationError as exc:
        warning("SSO", "OAuth callback authentication failed for provider={}: {}", provider_id, exc)
        return RedirectResponse(
            url=f"{public_app_url()}/login?error=sso_failed",
            status_code=302,
        )

    exchange_token = create_sso_exchange_token(user_id)
    return RedirectResponse(
        url=build_spa_callback_redirect(exchange_token, redirect_after),
        status_code=302,
    )


@api_router.post("/exchange")
@limiter.limit("30/minute")
async def sso_exchange(
    request: Request,
    body: SsoExchangeRequest,
    session=Depends(get_session),
):
    try:
        user_id = decode_sso_exchange_token(body.exchange_token)
    except JWTError as exc:
        warning("SSO", "Invalid or expired SSO exchange token")
        raise AuthenticationError(message="Invalid or expired SSO exchange token") from exc

    user = await session.get(User, user_id)
    if user is None or user.banned:
        raise AuthenticationError(message="User account is not available")

    return build_token_response(user)


@admin_router.get("")
async def sso_settings_page(request: Request, db=Depends(require_admin_session)):
    addon = addon_registry.get("sso")
    config: dict[str, Any] = {}
    if addon is not None:
        config = dict(addon_registry.get_config("sso"))

    google = config.get("google", {})
    facebook = config.get("facebook", {})
    oidc_list = config.get("oidc_providers") or []
    oidc = oidc_list[0] if oidc_list else {}

    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            "sso_settings.html",
            "SSO Login",
            addon=addon,
            config=config,
            google=google,
            facebook=facebook,
            oidc=oidc,
            public_app_url=public_app_url(),
            api_base_url=api_base_url(),
            callback_urls={
                "google": callback_url("google"),
                "facebook": callback_url("facebook"),
                "oidc": callback_url(f"oidc_{oidc.get('provider_id', 'custom')}"),
            },
        ),
    )


@admin_router.get("/", include_in_schema=False)
async def sso_trailing_slash_redirect():
    return RedirectResponse(url=_CONFIGURE_URL, status_code=307)


@admin_router.post("/settings")
async def sso_save_settings(
    request: Request,
    db=Depends(require_admin_session),
):
    from app.addons.admin_helpers import require_addon_csrf

    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))

    def _secret_field(name: str) -> str:
        value = str(form.get(name, "") or "")
        return value

    oidc_provider_id = str(form.get("oidc_provider_id", "custom") or "custom").strip().lower()
    oidc_enabled = form.get("oidc_enabled") == "on"

    config = {
        "is_active": form.get("is_active") == "on",
        "google": {
            "enabled": form.get("google_enabled") == "on",
            "client_id": str(form.get("google_client_id", "") or ""),
            "client_secret": _secret_field("google_client_secret"),
        },
        "facebook": {
            "enabled": form.get("facebook_enabled") == "on",
            "app_id": str(form.get("facebook_app_id", "") or ""),
            "app_secret": _secret_field("facebook_app_secret"),
        },
        "oidc_providers": [],
    }

    if oidc_enabled or str(form.get("oidc_issuer_url", "") or "").strip():
        config["oidc_providers"] = [
            {
                "provider_id": oidc_provider_id,
                "display_name": str(form.get("oidc_display_name", "SSO") or "SSO"),
                "enabled": oidc_enabled,
                "issuer_url": str(form.get("oidc_issuer_url", "") or ""),
                "client_id": str(form.get("oidc_client_id", "") or ""),
                "client_secret": _secret_field("oidc_client_secret"),
                "scopes": str(form.get("oidc_scopes", "openid email profile") or "openid email profile"),
            }
        ]

    enabled = form.get("is_enabled") == "on"
    try:
        return await save_addon_from_form(
            db,
            "sso",
            config,
            enabled=enabled,
            redirect_url=_CONFIGURE_URL,
            flash_message="SSO configuration saved",
        )
    except Exception as exc:
        addon = addon_registry.get("sso")
        saved = dict(addon_registry.get_config("sso")) if addon else {}
        google = saved.get("google", {})
        facebook = saved.get("facebook", {})
        oidc_list = saved.get("oidc_providers") or []
        oidc = oidc_list[0] if oidc_list else {}
        return HTMLResponse(
            content=render_addon_admin_page(
                jinja_env,
                request,
                "sso_settings.html",
                "SSO Login",
                flash=f"Error saving config: {exc}",
                flash_type="error",
                addon=addon,
                config=saved,
                google=google,
                facebook=facebook,
                oidc=oidc,
                public_app_url=public_app_url(),
                api_base_url=api_base_url(),
                callback_urls={
                    "google": callback_url("google"),
                    "facebook": callback_url("facebook"),
                    "oidc": callback_url(f"oidc_{oidc.get('provider_id', 'custom')}"),
                },
            ),
        )
