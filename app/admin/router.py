"""
Admin router – root router for all /admin/* endpoints.

Mounts:
  - Jinja2-rendered routes from app.admin.routes
  - Static assets (CSS) from app.admin.static/
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

from app.admin.routes import router as routes_router

router = APIRouter()

# ── Jinja2 environment ─────────────────────────────────────────────────

_templates_dir = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_templates_dir)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Make the environment available to route handlers
router.jinja_env = _jinja_env  # type: ignore[attr-defined]


# ── Static files ───────────────────────────────────────────────────────

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    router.mount("/static", StaticFiles(directory=str(_static_dir)), name="admin_static")


# ── Include Jinja routes ──────────────────────────────────────────────

router.include_router(routes_router)


# ── Fallback: if Jinja routes module is missing ────────────────────────

if not routes_router.routes:

    @router.get("/", response_class=HTMLResponse)
    async def admin_home():
        return "<h1>Admin Panel</h1><p>Routes not yet configured.</p>"

    @router.get("/login")
    async def admin_login_page():
        return "<h1>Login</h1><p>Implement login template.</p>"
