from urllib.parse import quote, unquote

from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    Form,
    RedirectResponse,
    Request,
    _common_ctx,
    _render_error,
    _require_csrf,
    _template,
    require_admin_session,
    set_flash_cookie,
    settings,
)

router = APIRouter()

_REVEAL_COOKIE = "_oshkelosh_webhook_secret"


def _set_reveal_cookie(response, secret: str) -> None:
    response.set_cookie(
        key=_REVEAL_COOKIE,
        value=quote(secret, safe=""),
        httponly=True,
        max_age=settings.flash_cookie_max_age,
        path="/",
    )


def _pop_reveal_secret(request: Request, response) -> str:
    raw = request.cookies.get(_REVEAL_COOKIE, "")
    response.delete_cookie(key=_REVEAL_COOKIE, path="/")
    if not raw:
        return ""
    try:
        return unquote(raw)
    except ValueError:
        return raw


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.admin_prefix}{path}", status_code=302)


@router.get("/webhooks")
async def admin_webhooks(request: Request, db=Depends(require_admin_session)):
    """Configure the outbound HMAC webhook receiver."""
    from app.services.outbound_webhooks import (
        SELECTABLE_EVENTS,
        get_outbound_webhook_endpoint,
        mask_webhook_secret,
    )

    endpoint = await get_outbound_webhook_endpoint(db)
    response = _template(
        "webhooks.html",
        **_common_ctx(request, "Webhooks"),
        endpoint=endpoint,
        event_catalog=SELECTABLE_EVENTS,
        selected_events=set(endpoint.events or []),
        secret_mask=mask_webhook_secret(endpoint.secret),
        revealed_secret="",
        can_test=bool(endpoint.url and endpoint.secret),
    )
    revealed = _pop_reveal_secret(request, response)
    if revealed:
        response = _template(
            "webhooks.html",
            **_common_ctx(request, "Webhooks"),
            endpoint=endpoint,
            event_catalog=SELECTABLE_EVENTS,
            selected_events=set(endpoint.events or []),
            secret_mask=mask_webhook_secret(endpoint.secret),
            revealed_secret=revealed,
            can_test=bool(endpoint.url and endpoint.secret),
        )
        response.delete_cookie(key=_REVEAL_COOKIE, path="/")
    return response


@router.post("/webhooks")
async def admin_webhooks_save(
    request: Request,
    enabled: str = Form(""),
    url: str = Form("", max_length=L.URL_LEN),
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Save receiver URL, enabled flag, and selected events. Generates a secret on first save."""
    from app.core.exceptions import ValidationError
    from app.services.audit import admin_request_meta, diff_fields, log_change
    from app.services.outbound_webhooks import (
        endpoint_to_dict,
        get_outbound_webhook_endpoint,
        save_outbound_webhook_endpoint,
    )

    _require_csrf(request, csrf_token)
    if not db:
        return _render_error(request, "Database unavailable")

    form = await request.form()
    events = [str(v) for v in form.getlist("events")]

    try:
        before = endpoint_to_dict(await get_outbound_webhook_endpoint(db))
        endpoint, revealed = await save_outbound_webhook_endpoint(
            db,
            enabled=bool(enabled),
            url=url,
            events=events,
        )
        await db.commit()
        actor_user_id, ip_address = admin_request_meta(request)
        await log_change(
            db,
            actor_user_id=actor_user_id,
            action="update",
            resource_type="outbound_webhook",
            resource_id=1,
            changes=diff_fields(before, endpoint_to_dict(endpoint)),
            ip_address=ip_address,
            detail="Outbound webhook updated",
        )
        await db.commit()
        resp = _redirect("/webhooks")
        if revealed:
            _set_reveal_cookie(resp, revealed)
            set_flash_cookie(resp, "Webhook saved. Copy the signing secret now — it will not be shown again.")
        else:
            set_flash_cookie(resp, "Webhook saved")
        return resp
    except ValidationError as exc:
        return _render_error(request, exc.message)
    except Exception as exc:
        return _render_error(request, f"Failed to save webhook: {exc}")


@router.post("/webhooks/rotate")
async def admin_webhooks_rotate(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """Replace the HMAC secret and show the new value once."""
    from app.services.audit import admin_request_meta, log_change
    from app.services.outbound_webhooks import rotate_outbound_webhook_secret

    _require_csrf(request, csrf_token)
    if not db:
        return _render_error(request, "Database unavailable")

    _endpoint, revealed = await rotate_outbound_webhook_secret(db)
    actor_user_id, ip_address = admin_request_meta(request)
    await log_change(
        db,
        actor_user_id=actor_user_id,
        action="update",
        resource_type="outbound_webhook",
        resource_id=1,
        changes={"secret": {"from": "[redacted]", "to": "[changed]"}},
        ip_address=ip_address,
        detail="Outbound webhook secret rotated",
    )
    await db.commit()
    resp = _redirect("/webhooks")
    _set_reveal_cookie(resp, revealed)
    set_flash_cookie(resp, "New signing secret generated. Copy it now — it will not be shown again.")
    return resp


@router.post("/webhooks/test")
async def admin_webhooks_test(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    db=Depends(require_admin_session),
):
    """POST a signed webhook.test event to the saved URL."""
    from app.services.outbound_webhooks import get_outbound_webhook_endpoint, send_outbound_webhook_test

    _require_csrf(request, csrf_token)
    if not db:
        return _render_error(request, "Database unavailable")

    endpoint = await get_outbound_webhook_endpoint(db)
    if not endpoint.url or not endpoint.secret:
        resp = _redirect("/webhooks")
        set_flash_cookie(resp, "Save a URL first, then send a test event.")
        return resp

    ok = await send_outbound_webhook_test(db)
    await db.commit()
    resp = _redirect("/webhooks")
    if ok:
        set_flash_cookie(resp, "Test event delivered")
    else:
        set_flash_cookie(resp, "Test event failed. Check the last delivery status below.")
    return resp
