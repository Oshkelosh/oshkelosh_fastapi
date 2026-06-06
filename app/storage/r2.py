"""Cloudflare R2 storage backend (S3-compatible API)."""

from app.config import Settings
from app.services.r2 import R2Service


class R2StorageBackend:
    """Object storage via Cloudflare R2."""

    def __init__(self, settings: Settings) -> None:
        if not (
            settings.r2_account_id
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
            and settings.r2_bucket_name
        ):
            raise ValueError("R2 credentials are not configured")
        self._service = R2Service(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket_name,
            public_base_url=settings.r2_public_base_url,
        )

    async def upload(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return await self._service.upload_bytes(key, content, content_type)

    async def delete(self, key: str) -> None:
        await self._service.delete_file(key)

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        return await self._service.generate_presigned_url(key, expires_in=expires_in)
