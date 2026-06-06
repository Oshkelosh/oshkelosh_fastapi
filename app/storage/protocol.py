"""Storage backend protocol."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Object storage operations used by media endpoints."""

    async def upload(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Persist object and return its public URL."""
        ...

    async def delete(self, key: str) -> None:
        """Remove object by key."""
        ...

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a URL to access the object (presigned for R2, direct for local)."""
        ...
