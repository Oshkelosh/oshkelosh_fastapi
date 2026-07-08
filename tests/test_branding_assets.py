"""Tests for branding asset processing and admin upload routes."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.admin.session import SESSION_COOKIE_NAME, decode_session, encode_session
from app.services.branding_assets import (
    branding_key_from_url,
    process_branding_image,
    upload_branding_asset,
)
from app.services.site_settings import get_site_settings


def _admin_session(user_id: int) -> tuple[dict[str, str], str]:
    token = encode_session(user_id)
    csrf = decode_session(token)["csrf"]
    return {SESSION_COOKIE_NAME: token}, csrf


def _tiny_png_bytes() -> bytes:
    image = Image.new("RGB", (120, 80), color=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _storage_mock(base_url: str = "http://testserver/media/files") -> MagicMock:
    storage = MagicMock()

    async def _upload(key: str, content: bytes, content_type: str) -> str:
        del content, content_type
        return f"{base_url}/{key}"

    storage.upload = AsyncMock(side_effect=_upload)
    storage.delete = AsyncMock()
    return storage


def test_process_branding_logo_resizes_to_max_edge():
    large = Image.new("RGB", (1200, 600), color=(0, 128, 255))
    buffer = BytesIO()
    large.save(buffer, format="PNG")

    processed = process_branding_image(
        buffer.getvalue(),
        kind="logo",
        source_content_type="image/png",
    )
    image = Image.open(BytesIO(processed))
    assert max(image.size) <= 512
    assert processed[:4] == b"RIFF"


def test_process_branding_favicon_is_square():
    processed = process_branding_image(
        _tiny_png_bytes(),
        kind="favicon",
        source_content_type="image/png",
    )
    image = Image.open(BytesIO(processed))
    assert image.size == (48, 48)


def test_branding_key_from_url():
    url = "http://testserver/media/files/branding/logo.webp"
    assert branding_key_from_url(url) == "branding/logo.webp"
    assert branding_key_from_url("https://external.example/logo.png") is None


@pytest.mark.asyncio
async def test_upload_branding_asset_stores_fixed_key():
    storage = _storage_mock()
    url = await upload_branding_asset(
        "logo",
        _tiny_png_bytes(),
        "image/png",
        storage=storage,
    )
    assert url.endswith("/branding/logo.webp")
    storage.upload.assert_awaited_once()
    assert storage.upload.await_args.args[0] == "branding/logo.webp"


@pytest.mark.asyncio
async def test_admin_logo_upload(client: AsyncClient, test_user, db_session):
    cookies, csrf = _admin_session(test_user.id)
    storage = _storage_mock()

    with patch("app.storage.get_storage", return_value=storage):
        response = await client.post(
            "/admin/settings/logo",
            cookies=cookies,
            data={"csrf_token": csrf},
            files={"file": ("logo.png", BytesIO(_tiny_png_bytes()), "image/png")},
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin/settings"
    site = await get_site_settings(db_session)
    assert site.logo_url == "http://testserver/media/files/branding/logo.webp"
    storage.upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_favicon_clear(client: AsyncClient, test_user, db_session):
    from app.services.site_settings import update_site_settings

    await update_site_settings(
        db_session,
        {"favicon_url": "http://testserver/media/files/branding/favicon.webp"},
    )
    cookies, csrf = _admin_session(test_user.id)
    storage = _storage_mock()

    with patch("app.storage.get_storage", return_value=storage):
        response = await client.post(
            "/admin/settings/favicon/clear",
            cookies=cookies,
            data={"csrf_token": csrf},
        )

    assert response.status_code == 302
    site = await get_site_settings(db_session)
    assert site.favicon_url is None
    storage.delete.assert_awaited_once_with("branding/favicon.webp")
