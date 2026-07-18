"""
FastAPI application factory for Oshkelosh.

Sets up the lifespan (startup / shutdown), mounts the API, admin,
and SPA static files, and registers middleware.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import settings, validate_backends
from app.core.middleware import register_middleware

# ------------------------------------------------------------------
# Loguru configuration (overrides default logging)
# ------------------------------------------------------------------

def _configure_logging() -> None:
    """Configure loguru as the primary logging backend."""
    # Remove default handler
    logger.remove()
    # Console handler
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    # Bind loguru to the standard ``logging`` module so third-party
    # libraries can still emit logs.
    class LoguruHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logger_opt = logger.opt(depth=1, exception=record.exc_info)
            if record.levelno >= logging.ERROR:
                logger_opt.error(record.getMessage())
            elif record.levelno >= logging.WARNING:
                logger_opt.warning(record.getMessage())
            elif record.levelno >= logging.INFO:
                logger_opt.info(record.getMessage())
            else:
                logger_opt.debug(record.getMessage())

    logging.getLogger().addHandler(LoguruHandler())


# ------------------------------------------------------------------
# Lifespan
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: initialise on startup, clean up on shutdown."""
    # Startup
    _configure_logging()
    logger.info("🚀 Starting {} (env={})", settings.app_name, settings.app_env)

    from app.db.base import auto_create_tables_async
    from app.db.connection import get_d1
    from app.storage import get_storage

    validate_backends(settings)
    from app.config import _DEFAULT_JWT_SECRET

    if settings.jwt_secret_key == _DEFAULT_JWT_SECRET and settings.app_env != "production":
        logger.warning(
            "JWT_SECRET_KEY is the default placeholder — set a strong secret before production"
        )
    logger.info(
        "Backends: database={} storage={} profile={}",
        settings.database_backend,
        settings.storage_backend,
        settings.deployment_profile,
    )

    await auto_create_tables_async()
    from app.db.migrations import apply_migrations_async

    await apply_migrations_async()
    if settings.database_backend == "d1_http":
        get_d1()
    get_storage()

    from app.addons import addon_registry
    from app.db.connection import session_scope
    from app.services.bootstrap import has_admin_user
    from app.services.pending_order_cleanup import process_stale_pending_orders

    async with session_scope() as session:
        app.state.needs_setup = not await has_admin_user(session)
        await addon_registry.startup(session)
        cleanup_result = await process_stale_pending_orders(session)
        if cleanup_result.scanned:
            logger.info(cleanup_result.summary_message())

    from app.services.addons import get_frontend_addon

    frontend = get_frontend_addon()
    if frontend is not None:
        logger.info(
            "Active storefront frontend: '{}' (dynamic handler at /)",
            frontend.addon_id,
        )
    else:
        logger.info("No storefront frontend enabled (dynamic handler at /)")

    if app.state.needs_setup:
        logger.info("No admin user found — visit /setup to create the first account")
    logger.info("Application ready")

    yield  # <-- app runs while this is open

    # Shutdown
    logger.info("🛑 Shutting down {} ...", settings.app_name)
    from app.addons import addon_registry as _addon_registry

    await _addon_registry.shutdown()
    from app.db.connection import close_all_connections
    await close_all_connections()
    logger.info("👋 Goodbye")


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------

def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns the fully configured ``FastAPI`` instance ready to be
    served by an ASGI server (e.g. Uvicorn).
    """
    from app.openapi import OPENAPI_DESCRIPTION, OPENAPI_TAGS

    openapi_description = OPENAPI_DESCRIPTION
    openapi_tags = OPENAPI_TAGS

    app = FastAPI(
        title=settings.app_name,
        description=openapi_description,
        version="0.1.0",
        openapi_tags=openapi_tags,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # Middleware (CORS, request-ID, exception handling, timing)
    register_middleware(app)
    from app.core.rate_limit import register_rate_limiting

    register_rate_limiting(app)

    # ------------------------------------------------------------------
    # API routers  –  /api/v1/*
    # ------------------------------------------------------------------
    from app.api.v1.router import router as api_v1_router
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    # ------------------------------------------------------------------
    # Admin routes  –  /admin/*
    # ------------------------------------------------------------------
    try:
        from app.admin.router import router as admin_router
        from app.addons.mount import mount_addon_routers

        mount_addon_routers(app, settings.api_v1_prefix, admin_router)
        app.include_router(admin_router, prefix=settings.admin_prefix)

        # The SPA catch-all mount at "/" swallows Starlette's automatic
        # trailing-slash redirect, so map /admin -> /admin/ explicitly.
        @app.get(settings.admin_prefix, include_in_schema=False)
        async def admin_root_redirect():
            from fastapi.responses import RedirectResponse

            return RedirectResponse(url=f"{settings.admin_prefix}/", status_code=307)
    except ImportError:
        logger.warning("Admin router not found – skipping admin routes")
        from app.addons.mount import mount_addon_routers

        mount_addon_routers(app, settings.api_v1_prefix, APIRouter())

    # ------------------------------------------------------------------
    # First-run setup  –  /setup (before SPA catch-all)
    # ------------------------------------------------------------------
    from app.setup.routes import router as setup_router

    app.include_router(setup_router)

    # ------------------------------------------------------------------
    # Local media files (storage_backend=local)
    # ------------------------------------------------------------------
    from app.config import LOCAL_MEDIA_MOUNT_PATH

    if settings.storage_backend == "local":
        media_dir = settings.local_media_path
        media_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            f"/{LOCAL_MEDIA_MOUNT_PATH}",
            StaticFiles(directory=str(media_dir)),
            name="local_media",
        )
        logger.info("Local media mounted at /{} from {}", LOCAL_MEDIA_MOUNT_PATH, media_dir)

    # ------------------------------------------------------------------
    # Health-check endpoint
    # ------------------------------------------------------------------
    @app.get("/health", tags=["internal"])
    async def health_check():
        if settings.app_env == "production" and not settings.debug:
            return {"status": "ok"}
        return {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.app_env,
            "debug": settings.debug,
            "deployment_profile": settings.deployment_profile,
            "database_backend": settings.database_backend,
            "storage_backend": settings.storage_backend,
        }

    @app.get("/health/ready", tags=["internal"])
    async def health_ready():
        """Readiness probe: database and storage must be reachable."""
        from fastapi.responses import JSONResponse

        from app.services.system_health import run_infrastructure_checks

        checks, ok = await run_infrastructure_checks()
        body = {"status": "ready" if ok else "not_ready", "checks": checks}
        if settings.app_env != "production" or settings.debug:
            body["database_backend"] = settings.database_backend
            body["storage_backend"] = settings.storage_backend
        return JSONResponse(status_code=200 if ok else 503, content=body)

    @app.get("/firebase-messaging-sw.js", include_in_schema=False)
    async def firebase_messaging_service_worker():
        from app.services.push_discovery import build_push_service_worker_js
        from fastapi.responses import Response

        js = build_push_service_worker_js()
        if js is None:
            return Response(status_code=404, content="Not found", media_type="text/plain")
        return Response(content=js, media_type="application/javascript")

    from app.storefront.auth_links import register_auth_link_routes
    from app.storefront.seo_routes import register_seo_routes
    from app.storefront.static import register_storefront_handler

    register_seo_routes(app)
    register_auth_link_routes(app)
    register_storefront_handler(app)

    return app


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
app = create_app()
