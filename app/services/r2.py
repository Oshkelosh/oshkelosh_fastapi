"""Cloudflare R2 service for media upload and retrieval."""

import logging
from typing import Optional

import boto3
from botocore.client import Config
from fastapi import UploadFile

logger = logging.getLogger(__name__)


class R2Service:
    """Interface to Cloudflare R2 for object storage operations."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str = "auto",
        public_base_url: Optional[str] = None,
    ):
        self.account_id = account_id
        self.bucket = bucket
        self.public_base_url = public_base_url
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3},
            ),
        )

    def public_url(self, key: str) -> str:
        """Return the public URL for an object key."""
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"
        return f"https://pub-{self.account_id}.r2.dev/{key}"

    async def upload_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to R2 and return the public URL."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return self.public_url(key)

    async def upload_file(
        self, key: str, file: UploadFile, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload a file to R2 and return the public URL."""
        contents = await file.read()
        return await self.upload_bytes(key, contents, content_type)

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for a file."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def delete_file(self, key: str) -> bool:
        """Delete a file from R2."""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error("Failed to delete %s: %s", key, e)
            return False

    async def file_exists(self, key: str) -> bool:
        """Check if a file exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    @staticmethod
    def validate_image(file: UploadFile) -> tuple[bool, str]:
        """Validate that an uploaded file is an acceptable image."""
        allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if file.content_type not in allowed_types:
            return (
                False,
                f"Unsupported type: {file.content_type}. "
                f"Allowed: {', '.join(sorted(allowed_types))}",
            )
        if file.size and file.size > 5 * 1024 * 1024:
            return False, "File too large. Maximum size is 5MB."
        return True, ""
