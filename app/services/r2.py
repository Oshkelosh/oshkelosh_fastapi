"""Cloudflare R2 service for media upload and retrieval."""

import asyncio
import logging
from typing import Optional

import boto3
from botocore.client import Config

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
        """Upload bytes to R2 and return the public URL (boto3 call off-loop)."""
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return self.public_url(key)

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for a file."""
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def delete_file(self, key: str) -> bool:
        """Delete a file from R2 (boto3 call off-loop)."""
        try:
            await asyncio.to_thread(
                self.client.delete_object, Bucket=self.bucket, Key=key
            )
            return True
        except Exception as e:
            logger.error("Failed to delete %s: %s", key, e)
            return False
