"""Tests for tool nav link and SEO/sitemap aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.tool_discovery import (
    list_storefront_nav_links,
    list_tool_sitemap_entries,
    resolve_tool_seo_meta,
)
from app.storefront.seo import render_sitemap_xml


def test_list_storefront_nav_links_dedupes_by_href():
    tool_a = MagicMock()
    tool_a.addon_id = "articles"
    tool_a.list_storefront_nav_links.return_value = [
        {"label": "Articles", "href": "/articles"},
        {"label": "Bad", "href": ""},
        "skip",
    ]
    tool_b = MagicMock()
    tool_b.addon_id = "other"
    tool_b.list_storefront_nav_links.return_value = [
        {"label": "Articles again", "href": "/articles"},
        {"label": "Docs", "href": "/docs"},
    ]
    with patch(
        "app.services.tool_discovery.get_enabled_tools",
        return_value=[tool_a, tool_b],
    ):
        links = list_storefront_nav_links()
    assert links == [
        {"label": "Articles", "href": "/articles"},
        {"label": "Docs", "href": "/docs"},
    ]


def test_resolve_tool_seo_meta_returns_first_with_title():
    empty = MagicMock()
    empty.addon_id = "noop"
    empty.resolve_seo_meta.return_value = None
    articles = MagicMock()
    articles.addon_id = "articles"
    articles.resolve_seo_meta.return_value = {
        "title": "Articles | Shop",
        "canonical_url": "https://shop.example/articles",
    }
    with patch(
        "app.services.tool_discovery.get_enabled_tools",
        return_value=[empty, articles],
    ):
        meta = resolve_tool_seo_meta(
            "/articles",
            site_url="https://shop.example",
            store_name="Shop",
        )
    assert meta is not None
    assert meta["title"] == "Articles | Shop"
    articles.resolve_seo_meta.assert_called_once()


def test_list_tool_sitemap_entries_and_render():
    tool = MagicMock()
    tool.addon_id = "articles"
    tool.list_sitemap_entries.return_value = [
        {"loc": "https://shop.example/articles", "lastmod": None},
        {"loc": "https://shop.example/articles/hello", "lastmod": "2026-01-02"},
        {"loc": "https://shop.example/articles", "lastmod": "ignored-dup"},
    ]
    with patch("app.services.tool_discovery.get_enabled_tools", return_value=[tool]):
        entries = list_tool_sitemap_entries("https://shop.example")
    assert entries == [
        {"loc": "https://shop.example/articles", "lastmod": None},
        {"loc": "https://shop.example/articles/hello", "lastmod": "2026-01-02"},
    ]
    xml = render_sitemap_xml(
        "https://shop.example",
        products=[],
        categories=[],
        extra_entries=[(e["loc"], e.get("lastmod")) for e in entries],
    )
    assert "<loc>https://shop.example/articles</loc>" in xml
    assert "<loc>https://shop.example/articles/hello</loc>" in xml
    assert "<lastmod>2026-01-02</lastmod>" in xml
