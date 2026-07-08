"""Tests for category API endpoints."""

from httpx import AsyncClient

from models.category import Category


class TestCategoryDetail:
    async def test_get_category_with_children(
        self, client: AsyncClient, db_session
    ):
        parent = Category(
            name="Canvas",
            slug="canvas-in-thin",
            description="Canvas prints",
            sort_order=0,
        )
        child = Category(
            name="Small",
            slug="canvas-small",
            description="Small canvas",
            sort_order=1,
        )
        db_session.add(parent)
        await db_session.flush()
        child.parent_id = parent.id
        db_session.add(child)
        await db_session.flush()

        response = await client.get("/api/v1/categories/canvas-in-thin")
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "canvas-in-thin"
        assert len(data["children"]) == 1
        assert data["children"][0]["slug"] == "canvas-small"

    async def test_get_category_not_found(self, client: AsyncClient):
        response = await client.get("/api/v1/categories/missing-slug")
        assert response.status_code == 404
