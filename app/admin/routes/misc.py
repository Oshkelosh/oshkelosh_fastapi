from fastapi import APIRouter

from app.admin import limits as L
from app.admin.routes._deps import (
    Request,
    STATIC_DIR,
    _render_error,
)

router = APIRouter()

@router.get("/error")
async def admin_error_page(request: Request, message: str = "An error occurred"):
    """Render the generic admin error page."""
    return _render_error(request, message)


from fastapi.responses import FileResponse

from starlette.requests import Request as StarletteRequest


@router.get("/static/{path:path}")
async def admin_static(path: str):
    """Serve admin static files (CSS, JS, images)."""
    static_root = STATIC_DIR.resolve()
    file_path = (STATIC_DIR / path).resolve()
    try:
        file_path.relative_to(static_root)
    except ValueError:
        return FileResponse(str(STATIC_DIR / "404.png"), status_code=404)
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    return FileResponse(str(STATIC_DIR / "404.png"), status_code=404)
