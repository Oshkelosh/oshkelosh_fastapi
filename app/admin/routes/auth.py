from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Depends,
    Form,
    RedirectResponse,
    Request,
    SESSION_COOKIE_NAME,
    _SETUP_PATH,
    _common_ctx,
    _needs_setup,
    clear_session_cookie,
    get_session,
    jinja_env,
    limiter,
    select,
    set_session_cookie,
    settings,
    verify_password,
)

router = APIRouter()

@router.get("/login")
async def admin_login_page(request: Request):
    """Show the admin login form."""
    from fastapi.responses import HTMLResponse

    if _needs_setup(request):
        return RedirectResponse(url=_SETUP_PATH, status_code=302)

    # Already logged in – redirect to dashboard
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(
            url=f"{settings.admin_prefix}/dashboard",
            status_code=302,
        )

    return HTMLResponse(
        content=jinja_env.get_template("login.html").render(
            **_common_ctx(request, "Admin Login", flash=""),
            redirect_to="/dashboard",
            error="",
        ),
    )


@router.post("/login")
@limiter.limit(settings.rate_limit_admin_login)
async def admin_login_submit(
    request: Request,
    email: str = Form(..., max_length=L.EMAIL_LEN),
    password: str = Form(..., max_length=L.PASSWORD_LEN),
    session=Depends(get_session),
):
    """Authenticate the admin and create a session cookie."""
    from fastapi.responses import HTMLResponse
    from models.user import User

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="Invalid email or password",
            ),
        )

    if not user.is_admin:
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="You do not have admin privileges",
            ),
        )

    if user.banned:
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="Account is banned",
            ),
        )

    if not user.verified:
        return HTMLResponse(
            content=jinja_env.get_template("login.html").render(
                **_common_ctx(request, "Admin Login", flash=""),
                redirect_to="/dashboard",
                error="Email address is not verified",
            ),
        )

    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    set_session_cookie(resp, user.id)
    return resp


@router.get("/logout")
async def admin_logout(request: Request):
    """Destroy the session and redirect to the login page."""
    resp = RedirectResponse(url="/admin/login", status_code=302)
    clear_session_cookie(resp)
    return resp


