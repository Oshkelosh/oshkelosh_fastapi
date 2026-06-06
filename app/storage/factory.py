"""Storage backend factory."""

from typing import Optional

from app.config import Settings, get_settings
from app.storage.local import LocalStorageBackend
from app.storage.protocol import StorageBackend
from app.storage.r2 import R2StorageBackend

_storage: Optional[StorageBackend] = None


def create_storage(settings: Settings | None = None) -> StorageBackend:
    """Build a storage backend from settings."""
    cfg = settings or get_settings()
    if cfg.storage_backend == "local":
        return LocalStorageBackend(cfg)
    if cfg.storage_backend == "r2":
        return R2StorageBackend(cfg)
    raise ValueError(f"Unknown storage_backend: {cfg.storage_backend}")


def get_storage() -> StorageBackend:
    """Return the singleton storage backend instance."""
    global _storage
    if _storage is None:
        _storage = create_storage()
    return _storage


def reset_storage() -> None:
    """Clear cached storage (for tests)."""
    global _storage
    _storage = None
