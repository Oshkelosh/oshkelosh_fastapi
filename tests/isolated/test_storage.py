"""Storage tests (isolated from main conftest / app import)."""

from pathlib import Path

import pytest

from app.config import Settings, reload_settings
from app.storage.factory import create_storage, reset_storage
from app.storage.local import LocalStorageBackend


@pytest.fixture
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("LOCAL_MEDIA_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LOCAL_MEDIA_BASE_URL", "http://testserver/media/files")
    reload_settings()
    reset_storage()
    cfg = Settings()
    backend = create_storage(cfg)
    yield backend, tmp_path
    reset_storage()
    reload_settings()


@pytest.mark.asyncio
async def test_local_storage_upload_and_url(local_storage):
    backend, tmp_path = local_storage
    assert isinstance(backend, LocalStorageBackend)

    key = "products/test-image.jpg"
    content = b"fake-image-bytes"
    url = await backend.upload(key, content, "image/jpeg")

    assert url == "http://testserver/media/files/products/test-image.jpg"
    file_path = tmp_path / "uploads" / "products" / "test-image.jpg"
    assert file_path.exists()
    assert file_path.read_bytes() == content

    resolved = await backend.get_url(key)
    assert resolved == url


@pytest.mark.asyncio
async def test_local_storage_delete(local_storage):
    backend, tmp_path = local_storage
    key = "products/remove-me.png"
    await backend.upload(key, b"data", "image/png")

    file_path = tmp_path / "uploads" / "products" / "remove-me.png"
    assert file_path.exists()

    await backend.delete(key)
    assert not file_path.exists()
