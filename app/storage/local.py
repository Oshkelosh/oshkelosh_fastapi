"""Local filesystem storage backend."""

from pathlib import Path

import aiofiles

from app.config import Settings


class LocalStorageBackend:
    """Store uploaded files on disk and serve via StaticFiles mount."""

    def __init__(self, settings: Settings) -> None:
        self._dir = settings.local_media_path
        self._base_url = settings.local_media_base_url.rstrip("/")
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        safe_key = key.lstrip("/").replace("..", "")
        path = self._dir / safe_key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _url_for_key(self, key: str) -> str:
        safe_key = key.lstrip("/")
        return f"{self._base_url}/{safe_key}"

    async def upload(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        del content_type  # not stored in metadata for local files
        path = self._path_for_key(key)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        return self._url_for_key(key)

    async def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        if path.exists():
            path.unlink()

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        del expires_in
        path = self._path_for_key(key)
        if not path.exists():
            raise FileNotFoundError(f"Media not found: {key}")
        return self._url_for_key(key)
