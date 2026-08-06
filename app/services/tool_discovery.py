"""Aggregate enabled tool addons for storefront and commerce hooks."""

from __future__ import annotations

import logging
from typing import Any

from app.services.addons import get_enabled_tools

logger = logging.getLogger(__name__)


def list_storefront_scripts() -> list[dict[str, Any]]:
    """Collect script injection metadata from all enabled tools."""
    scripts: list[dict[str, Any]] = []
    for tool in get_enabled_tools():
        try:
            entries = tool.list_storefront_scripts()
        except Exception:
            logger.exception("Tool '%s' list_storefront_scripts failed", tool.addon_id)
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id"):
                scripts.append(entry)
    return scripts


def list_storefront_nav_links() -> list[dict[str, str]]:
    """Collect storefront nav links from all enabled tools."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for tool in get_enabled_tools():
        try:
            entries = tool.list_storefront_nav_links()
        except Exception:
            logger.exception("Tool '%s' list_storefront_nav_links failed", tool.addon_id)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            href = str(entry.get("href") or "").strip()
            if not label or not href or href in seen:
                continue
            seen.add(href)
            links.append({"label": label, "href": href})
    return links


def list_tool_crawl_article_links(site_url: str) -> list[tuple[str, str]]:
    """Collect article title/URL pairs from enabled tools for SEO crawl menus."""
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tool in get_enabled_tools():
        try:
            entries = tool.list_crawl_article_links(site_url)
        except Exception:
            logger.exception(
                "Tool '%s' list_crawl_article_links failed", tool.addon_id
            )
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            href = str(entry.get("href") or "").strip()
            if not label or not href or href in seen:
                continue
            seen.add(href)
            links.append((label, href))
    return links


def resolve_tool_seo_meta(
    path: str,
    *,
    site_url: str,
    store_name: str,
    default_description: str | None = None,
    logo_url: str | None = None,
) -> dict[str, Any] | None:
    """Return the first tool-provided SEO payload for ``path``, or None."""
    for tool in get_enabled_tools():
        try:
            meta = tool.resolve_seo_meta(
                path,
                site_url=site_url,
                store_name=store_name,
                default_description=default_description,
                logo_url=logo_url,
            )
        except Exception:
            logger.exception("Tool '%s' resolve_seo_meta failed", tool.addon_id)
            continue
        if isinstance(meta, dict) and meta.get("title"):
            return meta
    return None


def list_tool_sitemap_entries(site_url: str) -> list[dict[str, str | None]]:
    """Collect sitemap entries from all enabled tools."""
    entries: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for tool in get_enabled_tools():
        try:
            rows = tool.list_sitemap_entries(site_url)
        except Exception:
            logger.exception("Tool '%s' list_sitemap_entries failed", tool.addon_id)
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            loc = str(row.get("loc") or "").strip()
            if not loc or loc in seen:
                continue
            seen.add(loc)
            lastmod = row.get("lastmod")
            entries.append(
                {
                    "loc": loc,
                    "lastmod": str(lastmod) if lastmod else None,
                }
            )
    return entries


async def dispatch_commerce_event(
    event_key: str,
    payload: dict[str, Any],
) -> None:
    """Notify enabled tools of a commerce measurement event (e.g. purchase)."""
    for tool in get_enabled_tools():
        try:
            await tool.on_commerce_event(event_key, payload)
        except Exception:
            logger.exception(
                "Tool '%s' failed handling commerce event '%s'",
                tool.addon_id,
                event_key,
            )


def build_purchase_payload(order: Any, user: Any | None = None) -> dict[str, Any]:
    from app.services.lifecycle_events import build_order_paid_payload

    return build_order_paid_payload(order, user)
