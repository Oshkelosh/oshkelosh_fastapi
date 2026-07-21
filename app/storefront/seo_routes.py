"""FastAPI routes for storefront SEO (sitemap, robots, injected HTML)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import load_only
from sqlmodel import col, select
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from app.db.connection import get_session
from app.services.site_settings import get_site_settings
from app.services.storefront_resolver import resolve_static_directory
from app.storefront.seo import (
    PRIVATE_SEO_PATHS,
    inject_seo_into_html,
    is_private_path,
    read_storefront_index_html,
    render_robots_txt,
    render_sitemap_xml,
    resolve_meta_for_path,
    resolve_site_url,
    SeoMeta,
)
from models.category import Category
from models.product import Product

router = APIRouter(tags=["seo"])

_SITEMAP_CACHE_CONTROL = "public, max-age=600"
_ROBOTS_CACHE_CONTROL = "public, max-age=600"
_CATALOG_HTML_CACHE_CONTROL = "public, max-age=60"
_PRIVATE_HTML_CACHE_CONTROL = "private, no-store"


async def _load_index_html() -> str | None:
    directory = resolve_static_directory()
    if directory is None:
        return None
    return read_storefront_index_html(directory)


def _html_response(content: str, *, cache_control: str | None = None) -> HTMLResponse:
    headers = {"Cache-Control": cache_control} if cache_control else None
    return HTMLResponse(content=content, headers=headers)


async def serve_spa_html(
    request: Request,
    session,
    *,
    inject_meta: bool = True,
) -> Response:
    """Return the SPA shell, optionally with injected SEO metadata."""
    page_html = await _load_index_html()
    if page_html is None:
        return HTMLResponse(
            content="<h1>Storefront unavailable</h1>",
            status_code=503,
        )

    if not inject_meta:
        return HTMLResponse(content=page_html)

    site_settings = await get_site_settings(session)
    site_url = resolve_site_url(request, site_settings)
    meta = await resolve_meta_for_path(request.url.path, session, site_settings, site_url)

    if meta is None and is_private_path(request.url.path):
        meta = SeoMeta(
            title=site_settings.store_name,
            description=site_settings.meta_description,
            canonical_url=f"{site_url}{request.url.path}",
            site_name=site_settings.store_name,
            robots="noindex, nofollow",
        )

    if meta is None:
        return HTMLResponse(content=page_html)

    cache_control = (
        _PRIVATE_HTML_CACHE_CONTROL
        if meta.robots.startswith("noindex")
        else _CATALOG_HTML_CACHE_CONTROL
    )
    return _html_response(inject_seo_into_html(page_html, meta), cache_control=cache_control)


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request, session=Depends(get_session)) -> Response:
    """Dynamic XML sitemap for public catalog URLs."""
    site_settings = await get_site_settings(session)
    site_url = resolve_site_url(request, site_settings)

    products_result = await session.execute(
        select(Product)
        .options(load_only(Product.slug, Product.updated_at))
        .where(col(Product.status) == "published", col(Product.slug).is_not(None))
        .order_by(Product.updated_at.desc())
    )
    categories_result = await session.execute(
        select(Category)
        .options(load_only(Category.slug, Category.updated_at))
        .order_by(Category.updated_at.desc())
    )
    products = products_result.scalars().all()
    categories = categories_result.scalars().all()

    privacy_policy = None
    if site_settings.privacy_policy_enabled and (site_settings.privacy_policy_body or "").strip():
        privacy_policy = (
            f"{site_url}/privacy",
            site_settings.privacy_policy_effective_date or None,
        )

    body = render_sitemap_xml(
        site_url,
        products=products,
        categories=categories,
        privacy_policy=privacy_policy,
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": _SITEMAP_CACHE_CONTROL},
    )


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request, session=Depends(get_session)) -> PlainTextResponse:
    """Robots directives for crawlers."""
    site_settings = await get_site_settings(session)
    site_url = resolve_site_url(request, site_settings)
    return PlainTextResponse(
        render_robots_txt(site_url),
        headers={"Cache-Control": _ROBOTS_CACHE_CONTROL},
    )


@router.get("/", include_in_schema=False)
async def storefront_home(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA home page with injected SEO metadata."""
    return await serve_spa_html(request, session)


@router.get("/products", include_in_schema=False)
async def storefront_products(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA products page with injected SEO metadata."""
    return await serve_spa_html(request, session)


@router.get("/products/{slug}", include_in_schema=False)
async def storefront_product_detail(
    slug: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve a product detail page; unknown slugs fall back to the plain SPA shell."""
    return await serve_spa_html(request, session)


@router.get("/categories", include_in_schema=False)
async def storefront_categories(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA categories index with injected SEO metadata."""
    return await serve_spa_html(request, session)


@router.get("/categories/{slug}", include_in_schema=False)
async def storefront_category_detail(
    slug: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve a category page; unknown slugs fall back to the plain SPA shell."""
    return await serve_spa_html(request, session)


@router.get("/privacy", include_in_schema=False)
async def storefront_privacy(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA privacy policy page with injected SEO metadata."""
    return await serve_spa_html(request, session)


@router.get("/orders/{order_id}", include_in_schema=False)
async def storefront_order_detail(
    order_id: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve order detail SPA shell with noindex metadata."""
    return await serve_spa_html(request, session)


@router.get("/auth/{rest:path}", include_in_schema=False)
async def storefront_auth_path(
    rest: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve auth SPA shells with noindex metadata."""
    return await serve_spa_html(request, session)


async def _private_spa_html(request: Request, session=Depends(get_session)) -> Response:
    return await serve_spa_html(request, session)


def register_seo_routes(app) -> None:
    """Register SEO routes on the FastAPI app before the static storefront mount."""
    for path in PRIVATE_SEO_PATHS:
        app.add_api_route(
            path,
            _private_spa_html,
            methods=["GET"],
            include_in_schema=False,
            name=f"seo_private_{path.strip('/').replace('/', '_')}",
        )
    app.include_router(router)
