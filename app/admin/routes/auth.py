from fastapi import APIRouter
import secrets

from app.admin import limits as L
from app.admin.session import cookie_secure
from app.admin.routes._deps import (
    Depends,
    Form,
    HTTPException,
    RedirectResponse,
    Request,
    SESSION_COOKIE_NAME,
    _SETUP_PATH,
    _common_ctx,
    _needs_setup,
    clear_session_cookie,
    decode_session,
    get_session,
    jinja_env,
    limiter,
    select,
    set_session_cookie,
    settings,
    verify_password,
)

router = APIRouter()
_LOGIN_CSRF_COOKIE = "_oshkelosh_admin_login_csrf"


def _verify_login_csrf(request: Request, csrf_token: str) -> None:
    expected = request.cookies.get(_LOGIN_CSRF_COOKIE, "")
    if not expected or csrf_token != expected:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def _render_login(request: Request, *, error: str = "", csrf_token: str | None = None):
    from fastapi.responses import HTMLResponse

    token = csrf_token or secrets.token_urlsafe(32)
    ctx = _common_ctx(request, "Admin Login", flash="")
    ctx["csrf_token"] = token
    response = HTMLResponse(
        content=jinja_env.get_template("login.html").render(
            **ctx,
            redirect_to=f"{settings.admin_prefix}/dashboard",
            error=error,
        )
    )
    if csrf_token is None:
        response.set_cookie(
            key=_LOGIN_CSRF_COOKIE,
            value=token,
            httponly=True,
            samesite="lax",
            secure=cookie_secure(),
            max_age=3600,
            path="/",
        )
    return response

@router.get("/login")
async def admin_login_page(request: Request):
    """Show the admin login form."""
    if _needs_setup(request):
        return RedirectResponse(url=_SETUP_PATH, status_code=302)

    # Already logged in – redirect to dashboard
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(
            url=f"{settings.admin_prefix}/dashboard",
            status_code=302,
        )

    return _render_login(request)


@router.post("/login")
@limiter.limit(settings.rate_limit_admin_login)
async def admin_login_submit(
    request: Request,
    email: str = Form(..., max_length=L.EMAIL_LEN),
    password: str = Form(..., max_length=L.PASSWORD_LEN),
    csrf_token: str = Form("", max_length=128),
    session=Depends(get_session),
):
    """Authenticate the admin and create a session cookie."""
    from models.user import User

    _verify_login_csrf(request, csrf_token)

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        return _render_login(
            request,
            error="Invalid email or password",
            csrf_token=request.cookies.get(_LOGIN_CSRF_COOKIE),
        )

    if not user.is_admin:
        return _render_login(
            request,
            error="You do not have admin privileges",
            csrf_token=request.cookies.get(_LOGIN_CSRF_COOKIE),
        )

    if user.banned:
        return _render_login(
            request,
            error="Account is banned",
            csrf_token=request.cookies.get(_LOGIN_CSRF_COOKIE),
        )

    if not user.verified:
        return _render_login(
            request,
            error="Email address is not verified",
            csrf_token=request.cookies.get(_LOGIN_CSRF_COOKIE),
        )

    resp = RedirectResponse(url=f"{settings.admin_prefix}/dashboard", status_code=302)
    set_session_cookie(resp, user.id)
    return resp


@router.post("/logout")
async def admin_logout(request: Request, csrf_token: str = Form("", max_length=128)):
    """Destroy the session and redirect to the login page."""
    payload = decode_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    expected = (payload or {}).get("csrf", "")
    if not expected or csrf_token != expected:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    resp = RedirectResponse(url=f"{settings.admin_prefix}/login", status_code=302)
    clear_session_cookie(resp)
    return resp


