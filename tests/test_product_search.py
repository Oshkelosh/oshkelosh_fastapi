"""Tests for product search strategy hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import select

from app.services.product_search import apply_core_search_filter, get_search_tool, search_products
from models.product import Product


class TestProductSearch:
    def test_apply_core_search_filter(self):
        stmt = select(Product)
        filtered = apply_core_search_filter(stmt, "widget")
        assert filtered is not None

    def test_get_search_tool_none_when_disabled(self):
        with patch("app.services.product_search.get_enabled_tools", return_value=[]):
            assert get_search_tool() is None

    @pytest.mark.asyncio
    async def test_delegates_to_tool_when_enabled(self, db_session):
        mock_tool = MagicMock()
        mock_tool.supports_product_search = MagicMock(return_value=True)
        mock_tool.search_products = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 1}
        )

        with patch("app.services.product_search.get_enabled_tools", return_value=[mock_tool]):
            with patch("app.services.product_search.get_search_tool", return_value=mock_tool):
                result = await search_products(
                    db_session,
                    select(Product),
                    "shirt",
                    page=1,
                    page_size=20,
                )

        assert result is not None
        assert result["total"] == 0
        mock_tool.search_products.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_without_search_query(self, db_session):
        result = await search_products(db_session, select(Product), None)
        assert result is None
