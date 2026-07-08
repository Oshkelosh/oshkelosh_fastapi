"""First-admin setup routes at /setup."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError

from app.admin.session import set_session_cookie
from app.config import settings
from app.core.exceptions import ValidationError
from app.db.connection import get_session
from app.services.bootstrap import create_initial_admin, has_admin_user

router = APIRouter(tags=["setup"])

_SETUP_CSRF_COOKIE = "_oshkelosh_setup_csrf"


def _verify_setup_csrf(request: Request, csrf_token: str) -> None:
    expected = request.cookies.get(_SETUP_CSRF_COOKIE, "")
    if not expected or csrf_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render_setup(error: str = "", csrf_token: str | None = None) -> HTMLResponse:
    token = csrf_token or secrets.token_urlsafe(32)
    response = HTMLResponse(
        content=jinja_env.get_template("setup.html").render(
            title="Initial Setup",
            app_name=settings.app_name,
            error=error,
            csrf_token=token,
        ),
    )
    if csrf_token is None:
        response.set_cookie(
            key=_SETUP_CSRF_COOKIE,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=3600,
        )
    return response


@router.get("/setup")
async def setup_page(request: Request, session=Depends(get_session)):
    """Show the first-admin setup form."""
    if not getattr(request.app.state, "needs_setup", True):
        return RedirectResponse(url=f"{settings.admin_prefix}/login", status_code=302)

    if not await has_admin_user(session):
        return _render_setup()

    request.app.state.needs_setup = False
    return RedirectResponse(url=f"{settings.admin_prefix}/login", status_code=302)


@router.post("/setup")
async def setup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    full_name: str = Form(""),
    csrf_token: str = Form("", max_length=128),
    session=Depends(get_session),
):
    """Create the first admin user and sign in."""
    if await has_admin_user(session):
        return RedirectResponse(url=f"{settings.admin_prefix}/login", status_code=302)

    _verify_setup_csrf(request, csrf_token)

    if password != password_confirm:
        return _render_setup(
            "Passwords do not match.",
            csrf_token=request.cookies.get(_SETUP_CSRF_COOKIE),
        )

    try:
        user = await create_initial_admin(
            session,
            email=email.strip(),
            password=password,
            full_name=full_name.strip() or None,
        )
        user_id = user.id
    except ValidationError as exc:
        return _render_setup(
            exc.message,
            csrf_token=request.cookies.get(_SETUP_CSRF_COOKIE),
        )
    except IntegrityError:
        return _render_setup(
            "An admin user already exists.",
            csrf_token=request.cookies.get(_SETUP_CSRF_COOKIE),
        )
    except PydanticValidationError as exc:
        messages = [err.get("msg", str(err)) for err in exc.errors()]
        return _render_setup(
            "; ".join(messages),
            csrf_token=request.cookies.get(_SETUP_CSRF_COOKIE),
        )

    request.app.state.needs_setup = False
    resp = RedirectResponse(url=f"{settings.admin_prefix}/dashboard", status_code=302)
    set_session_cookie(resp, user_id)
    return resp
