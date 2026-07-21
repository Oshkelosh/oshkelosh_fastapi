"""SEO metadata resolution and HTML injection for the storefront SPA."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from sqlmodel import col, select
from starlette.requests import Request

from app.services.product_variants import get_active_variants
from models.category import Category
from models.product import Product
from models.product_image import ProductImage
from models.product_variant import ProductVariant
from models.site_settings import DEFAULT_PRIVACY_POLICY_TITLE, SiteSettings

PRIVATE_PATH_PREFIXES = (
    "/login",
    "/register",
    "/checkout",
    "/account",
    "/orders",
    "/cart",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/auth/",
)

# Exact SPA paths that need crawler noindex HTML (before the static mount).
# Omit /verify-email and /reset-password — owned by auth_links.
PRIVATE_SEO_PATHS = (
    "/cart",
    "/checkout",
    "/account",
    "/orders",
    "/login",
    "/register",
    "/forgot-password",
)

DEFAULT_CURRENCY = "USD"
_TITLE_MAX = 60
_DESCRIPTION_MAX = 160


@dataclass
class SeoMeta:
    """Resolved SEO tags for a storefront path."""

    title: str
    description: str | None = None
    canonical_url: str = ""
    og_type: str = "website"
    og_image: str | None = None
    site_name: str | None = None
    robots: str = "index, follow"
    json_ld: list[dict[str, Any]] = field(default_factory=list)


def resolve_site_url(request: Request, site_settings: SiteSettings) -> str:
    """Return the canonical public site URL for SEO routes."""
    from app.services.site_settings import resolve_public_site_url

    return resolve_public_site_url(site_settings=site_settings, request=request)


def truncate_text(text: str | None, max_len: int) -> str | None:
    """Truncate text for meta descriptions."""
    if not text:
        return None
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def is_private_path(path: str) -> bool:
    """Return True when a SPA path should not be indexed."""
    normalized = path if path.startswith("/") else f"/{path}"
    return any(normalized.startswith(prefix) for prefix in PRIVATE_PATH_PREFIXES)


def build_organization_json_ld(site_settings: SiteSettings, site_url: str) -> dict[str, Any]:
    """Build schema.org Organization JSON-LD."""
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": site_settings.store_name,
        "url": site_url,
    }
    if site_settings.logo_url:
        payload["logo"] = site_settings.logo_url
    return payload


def build_breadcrumb_json_ld(items: list[tuple[str, str]]) -> dict[str, Any]:
    """Build schema.org BreadcrumbList JSON-LD."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index + 1,
                "name": name,
                "item": url,
            }
            for index, (name, url) in enumerate(items)
        ],
    }


def _format_price_cents(cents: int) -> str:
    return f"{cents / 100:.2f}"


def _availability_url(in_stock: bool) -> str:
    return (
        "https://schema.org/InStock"
        if in_stock
        else "https://schema.org/OutOfStock"
    )


def build_product_offers_json_ld(
    product: Product,
    site_url: str,
    variants: list[ProductVariant],
    *,
    currency: str = DEFAULT_CURRENCY,
) -> dict[str, Any]:
    """Build schema.org Offer or AggregateOffer for a product listing."""
    product_url = f"{site_url}/products/{product.slug}"
    active = get_active_variants(variants)
    currency_code = currency.upper()

    if product.has_variants and len(active) > 1:
        prices = [variant.price_cents for variant in active]
        in_stock = any(variant.inventory_quantity > 0 for variant in active)
        return {
            "@type": "AggregateOffer",
            "lowPrice": _format_price_cents(min(prices)),
            "highPrice": _format_price_cents(max(prices)),
            "priceCurrency": currency_code,
            "offerCount": len(active),
            "availability": _availability_url(in_stock),
            "url": product_url,
        }

    variant = active[0] if active else None
    price_cents = variant.price_cents if variant is not None else product.price_cents
    inventory = variant.inventory_quantity if variant is not None else product.inventory_quantity
    return {
        "@type": "Offer",
        "price": _format_price_cents(price_cents),
        "priceCurrency": currency_code,
        "availability": _availability_url(inventory > 0),
        "url": product_url,
    }


def build_product_json_ld(
    product: Product,
    site_url: str,
    image_url: str | None,
    variants: list[ProductVariant] | None = None,
    *,
    currency: str = DEFAULT_CURRENCY,
) -> dict[str, Any]:
    """Build schema.org Product JSON-LD."""
    active = get_active_variants(variants or [])
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "url": f"{site_url}/products/{product.slug}",
        "offers": build_product_offers_json_ld(
            product,
            site_url,
            variants or [],
            currency=currency,
        ),
    }
    if product.description:
        payload["description"] = product.description
    sku = active[0].sku if len(active) == 1 and active[0].sku else product.sku
    if sku:
        payload["sku"] = sku
    if image_url:
        payload["image"] = [image_url]
    return payload


async def _product_primary_image(session: Any, product: Product) -> str | None:
    """Return the best product image URL, preferring shared (non-variant) images."""
    result = await session.execute(
        select(ProductImage)
        .where(col(ProductImage.product_id) == product.id)
        .order_by(
            col(ProductImage.variant_id).is_not(None),
            ProductImage.sort_order.asc(),
        )
        .limit(1)
    )
    image = result.scalar_one_or_none()
    return image.url if image is not None else None


async def resolve_meta_for_path(
    path: str,
    session: Any,
    site_settings: SiteSettings,
    site_url: str,
) -> SeoMeta | None:
    """Map a storefront path to SEO metadata."""
    normalized = path.rstrip("/") or "/"
    store_name = site_settings.store_name
    default_description = site_settings.meta_description

    if normalized == "/":
        return SeoMeta(
            title=store_name,
            description=default_description,
            canonical_url=f"{site_url}/",
            site_name=store_name,
            og_image=site_settings.logo_url,
            json_ld=[build_organization_json_ld(site_settings, site_url)],
        )

    if normalized == "/products":
        return SeoMeta(
            title=f"Products | {store_name}",
            description=default_description or f"Browse products at {store_name}",
            canonical_url=f"{site_url}/products",
            site_name=store_name,
            og_image=site_settings.logo_url,
        )

    if normalized == "/categories":
        return SeoMeta(
            title=f"Categories | {store_name}",
            description=default_description or f"Browse categories at {store_name}",
            canonical_url=f"{site_url}/categories",
            site_name=store_name,
            og_image=site_settings.logo_url,
        )

    if normalized == "/privacy":
        title = (site_settings.privacy_policy_title or DEFAULT_PRIVACY_POLICY_TITLE).strip() or (
            DEFAULT_PRIVACY_POLICY_TITLE
        )
        published = bool(
            site_settings.privacy_policy_enabled
            and (site_settings.privacy_policy_body or "").strip()
        )
        return SeoMeta(
            title=f"{title} | {store_name}",
            description=(
                truncate_text(site_settings.privacy_policy_body, _DESCRIPTION_MAX)
                if published
                else default_description
            ),
            canonical_url=f"{site_url}/privacy",
            site_name=store_name,
            og_image=site_settings.logo_url,
            robots="index, follow" if published else "noindex, nofollow",
        )

    if normalized.startswith("/products/"):
        slug = normalized.removeprefix("/products/")
        if not slug:
            return None
        result = await session.execute(
            select(Product).where(
                col(Product.slug) == slug,
                col(Product.status) == "published",
            )
        )
        product = result.scalar_one_or_none()
        if product is None:
            return None

        variants_result = await session.execute(
            select(ProductVariant).where(col(ProductVariant.product_id) == product.id)
        )
        variants = list(variants_result.scalars().all())

        title = product.meta_title or f"{product.name} | {store_name}"
        description = (
            product.meta_description
            or truncate_text(product.description, _DESCRIPTION_MAX)
            or default_description
        )
        image_url = await _product_primary_image(session, product)
        canonical = f"{site_url}/products/{product.slug}"
        breadcrumbs = [
            ("Home", f"{site_url}/"),
            ("Products", f"{site_url}/products"),
            (product.name, canonical),
        ]
        return SeoMeta(
            title=truncate_text(title, _TITLE_MAX) or title,
            description=description,
            canonical_url=canonical,
            og_type="product",
            og_image=image_url or site_settings.logo_url,
            site_name=store_name,
            json_ld=[
                build_product_json_ld(
                    product,
                    site_url,
                    image_url,
                    variants,
                    currency=getattr(site_settings, "shop_currency", None) or DEFAULT_CURRENCY,
                ),
                build_breadcrumb_json_ld(breadcrumbs),
            ],
        )

    if normalized.startswith("/categories/"):
        slug = normalized.removeprefix("/categories/")
        if not slug:
            return None
        result = await session.execute(
            select(Category).where(col(Category.slug) == slug)
        )
        category = result.scalar_one_or_none()
        if category is None:
            return None

        title = category.meta_title or f"{category.name} | {store_name}"
        description = (
            category.meta_description
            or truncate_text(category.description, _DESCRIPTION_MAX)
            or default_description
        )
        canonical = f"{site_url}/categories/{category.slug}"
        breadcrumbs = [
            ("Home", f"{site_url}/"),
            ("Products", f"{site_url}/products"),
            (category.name, canonical),
        ]
        return SeoMeta(
            title=truncate_text(title, _TITLE_MAX) or title,
            description=description,
            canonical_url=canonical,
            og_image=site_settings.logo_url,
            site_name=store_name,
            json_ld=[build_breadcrumb_json_ld(breadcrumbs)],
        )

    if is_private_path(normalized):
        return SeoMeta(
            title=store_name,
            description=default_description,
            canonical_url=f"{site_url}{normalized}",
            site_name=store_name,
            robots="noindex, nofollow",
        )

    return None


def inject_seo_into_html(page_html: str, meta: SeoMeta) -> str:
    """Insert SEO tags before </head> and replace any existing <title>."""
    tags = _render_head_tags(meta)
    updated = re.sub(r"<title>.*?</title>", "", page_html, count=1, flags=re.IGNORECASE | re.DOTALL)
    if "</head>" in updated:
        return updated.replace("</head>", f"{tags}\n</head>", 1)
    return f"{tags}\n{updated}"


def _render_head_tags(meta: SeoMeta) -> str:
    """Render HTML head tags for a resolved SEO payload."""
    parts = [f"<title>{html.escape(meta.title)}</title>"]
    if meta.description:
        parts.append(
            f'<meta name="description" content="{html.escape(meta.description)}">'
        )
    if meta.canonical_url:
        parts.append(f'<link rel="canonical" href="{html.escape(meta.canonical_url)}">')
    parts.append(f'<meta property="og:title" content="{html.escape(meta.title)}">')
    if meta.description:
        parts.append(
            f'<meta property="og:description" content="{html.escape(meta.description)}">'
        )
    if meta.canonical_url:
        parts.append(f'<meta property="og:url" content="{html.escape(meta.canonical_url)}">')
    parts.append(f'<meta property="og:type" content="{html.escape(meta.og_type)}">')
    if meta.site_name:
        parts.append(
            f'<meta property="og:site_name" content="{html.escape(meta.site_name)}">'
        )
    if meta.og_image:
        parts.append(f'<meta property="og:image" content="{html.escape(meta.og_image)}">')
    parts.append('<meta name="twitter:card" content="summary_large_image">')
    parts.append(f'<meta name="twitter:title" content="{html.escape(meta.title)}">')
    if meta.description:
        parts.append(
            f'<meta name="twitter:description" content="{html.escape(meta.description)}">'
        )
    if meta.og_image:
        parts.append(
            f'<meta name="twitter:image" content="{html.escape(meta.og_image)}">'
        )
    parts.append(f'<meta name="robots" content="{html.escape(meta.robots)}">')
    for block in meta.json_ld:
        parts.append(
            '<script type="application/ld+json">'
            f"{json.dumps(block, ensure_ascii=False)}"
            "</script>"
        )
    return "\n".join(parts)


_index_html_cache: tuple[str, float, str] | None = None


def read_storefront_index_html(dist_directory: Path) -> str | None:
    """Read index.html from a storefront dist directory (mtime-cached)."""
    global _index_html_cache
    index_path = dist_directory / "index.html"
    if not index_path.is_file():
        return None
    path_key = str(index_path.resolve())
    mtime = index_path.stat().st_mtime
    if (
        _index_html_cache is not None
        and _index_html_cache[0] == path_key
        and _index_html_cache[1] == mtime
    ):
        return _index_html_cache[2]
    content = index_path.read_text(encoding="utf-8")
    _index_html_cache = (path_key, mtime, content)
    return content


def render_robots_txt(site_url: str) -> str:
    """Render robots.txt for the storefront."""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /cart",
        "Disallow: /checkout",
        "Disallow: /account",
        "Disallow: /orders",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /forgot-password",
        "Disallow: /reset-password",
        "Disallow: /verify-email",
        f"Sitemap: {site_url}/sitemap.xml",
        "",
    ]
    return "\n".join(lines)


def _format_lastmod(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.date().isoformat()


def render_sitemap_xml(
    site_url: str,
    *,
    products: list[Product],
    categories: list[Category],
    privacy_policy: tuple[str, str | None] | None = None,
) -> str:
    """Render sitemap.xml for public catalog URLs.

    ``privacy_policy`` is an optional ``(loc, lastmod)`` entry for ``/privacy``.
    """
    entries: list[tuple[str, str | None]] = [
        (f"{site_url}/", None),
        (f"{site_url}/products", None),
        (f"{site_url}/categories", None),
    ]
    if privacy_policy is not None:
        entries.append(privacy_policy)
    for product in products:
        if product.slug:
            entries.append((f"{site_url}/products/{product.slug}", _format_lastmod(product.updated_at)))
    for category in categories:
        entries.append(
            (f"{site_url}/categories/{category.slug}", _format_lastmod(category.updated_at))
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{xml_escape(loc)}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{xml_escape(lastmod)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)
