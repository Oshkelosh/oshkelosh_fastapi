"""Tests for admin HTML category routes."""

from httpx import AsyncClient
from sqlmodel import select

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from models.category import Category


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


class TestAdminCategoryRoutes:
    async def test_create_category_auto_generates_seo(
        self, client: AsyncClient, test_user, db_session
    ):
        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            "/admin/categories",
            cookies=cookies,
            data={
                "csrf_token": csrf,
                "name": "Wall Art",
                "slug": "wall-art",
                "description": "Decorative wall art",
                "sort_order": "0",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        result = await db_session.execute(
            select(Category).where(Category.slug == "wall-art")
        )
        category = result.scalar_one()
        assert category.meta_title == "Wall Art | Oshkelosh"
        assert category.meta_description == "Decorative wall art"

    async def test_edit_form_loads(self, client: AsyncClient, test_user, db_session):
        category = Category(name="Prints", slug="prints", sort_order=0)
        db_session.add(category)
        await db_session.flush()

        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get("/admin/categories/prints/edit", cookies=cookies)

        assert response.status_code == 200
        assert "Edit Category" in response.text
        assert "prints" in response.text

    async def test_update_category(self, client: AsyncClient, test_user, db_session):
        category = Category(name="Prints", slug="prints", sort_order=0)
        db_session.add(category)
        await db_session.flush()

        cookies, csrf = _admin_session(test_user.id)
        response = await client.post(
            "/admin/categories/prints/edit",
            cookies=cookies,
            data={
                "csrf_token": csrf,
                "name": "Art Prints",
                "slug": "art-prints",
                "description": "Updated description",
                "sort_order": "2",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/admin/categories"

        await db_session.refresh(category)
        assert category.name == "Art Prints"
        assert category.slug == "art-prints"
        assert category.description == "Updated description"
        assert category.sort_order == 2

    async def test_edit_missing_category_returns_error_page(
        self, client: AsyncClient, test_user
    ):
        cookies, _csrf = _admin_session(test_user.id)
        response = await client.get("/admin/categories/missing/edit", cookies=cookies)

        assert response.status_code == 404
        assert "Category not found" in response.text
