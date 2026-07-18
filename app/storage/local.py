"""Local filesystem storage backend."""

from pathlib import Path

import aiofiles

from app.config import Settings


class LocalStorageBackend:
    """Store uploaded files on disk and serve via StaticFiles mount."""

    def __init__(self, settings: Settings) -> None:
        self._dir = settings.local_media_path.resolve()
        self._base_url = settings.local_media_base_url.rstrip("/")
        self._dir.mkdir(parents=True, exist_ok=True)

    def _normalize_key(self, key: str) -> str:
        """Return a media-root-relative key or raise on traversal/absolute keys.

        ``"../x"`` used to become the absolute ``/x`` because ``Path(base) / "/x"``
        discards ``base``; guard by rejecting any component that escapes the root.
        """
        cleaned = key.strip()
        if not cleaned or cleaned.startswith(("/", "\\")) or Path(cleaned).is_absolute():
            raise ValueError(f"Media key must be relative: {key!r}")
        if ".." in Path(cleaned).parts:
            raise ValueError(f"Media key must not contain '..': {key!r}")
        candidate = (self._dir / cleaned).resolve()
        if candidate == self._dir or not candidate.is_relative_to(self._dir):
            raise ValueError(f"Media key escapes storage root: {key!r}")
        return candidate.relative_to(self._dir).as_posix()

    def _path_for_key(self, key: str) -> Path:
        path = self._dir / self._normalize_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _url_for_key(self, key: str) -> str:
        return f"{self._base_url}/{self._normalize_key(key)}"

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
