"""FastAPI routes for storefront SEO (sitemap, robots, injected HTML)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import col, select
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from app.db.connection import get_session
from app.services.site_settings import get_site_settings
from app.services.storefront_resolver import resolve_static_directory
from app.storefront.seo import (
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


async def _load_index_html(request: Request) -> str | None:
    directory = resolve_static_directory(request)
    if directory is None:
        return None
    return read_storefront_index_html(directory)


async def _serve_spa_html(
    request: Request,
    session,
    *,
    inject_meta: bool = True,
) -> Response:
    """Return the SPA shell, optionally with injected SEO metadata."""
    page_html = await _load_index_html(request)
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
            robots="noindex, nofollow",
        )

    if meta is None:
        return HTMLResponse(content=page_html)

    return HTMLResponse(content=inject_seo_into_html(page_html, meta))


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request, session=Depends(get_session)) -> Response:
    """Dynamic XML sitemap for public catalog URLs."""
    site_settings = await get_site_settings(session)
    site_url = resolve_site_url(request, site_settings)

    products_result = await session.execute(
        select(Product)
        .where(col(Product.status) == "published", col(Product.slug).is_not(None))
        .order_by(Product.updated_at.desc())
    )
    categories_result = await session.execute(
        select(Category).order_by(Category.updated_at.desc())
    )
    products = products_result.scalars().all()
    categories = categories_result.scalars().all()

    body = render_sitemap_xml(site_url, products=products, categories=categories)
    return Response(content=body, media_type="application/xml")


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request, session=Depends(get_session)) -> PlainTextResponse:
    """Robots directives for crawlers."""
    site_settings = await get_site_settings(session)
    site_url = resolve_site_url(request, site_settings)
    return PlainTextResponse(render_robots_txt(site_url))


@router.get("/", include_in_schema=False)
async def storefront_home(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA home page with injected SEO metadata."""
    return await _serve_spa_html(request, session)


@router.get("/products", include_in_schema=False)
async def storefront_products(request: Request, session=Depends(get_session)) -> Response:
    """Serve the SPA products page with injected SEO metadata."""
    return await _serve_spa_html(request, session)


@router.get("/products/{slug}", include_in_schema=False)
async def storefront_product_detail(
    slug: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve a product detail page; unknown slugs fall back to the plain SPA shell."""
    return await _serve_spa_html(request, session)


@router.get("/categories/{slug}", include_in_schema=False)
async def storefront_category_detail(
    slug: str,
    request: Request,
    session=Depends(get_session),
) -> Response:
    """Serve a category page; unknown slugs fall back to the plain SPA shell."""
    return await _serve_spa_html(request, session)


def register_seo_routes(app) -> None:
    """Register SEO routes on the FastAPI app before the static storefront mount."""
    app.include_router(router)
