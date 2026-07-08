"""Media upload endpoints (local filesystem or Cloudflare R2)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlmodel import col, select

from app.config import settings
from app.core.dependencies import CurrentUser, get_admin_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session
from app.services.product_images import (
    delete_product_image,
    read_upload_file,
    storage_key_from_url,
    upload_product_image,
    upload_standalone_image,
    variant_keys_from_primary_key,
    variant_urls_from_primary_url,
)
from app.storage import StorageBackend, get_storage
from models.product import Product
from models.product_image import ProductImage

router = APIRouter(prefix="/media", tags=["media"])

logger = logging.getLogger(__name__)

_ALLOWED_KEY_PREFIXES = ("products/", "media/", "branding/")


def _validate_media_key(key: str) -> str:
    """Reject path traversal and restrict to known storage prefixes."""
    if ".." in key or key.startswith("/"):
        raise ValidationError(message="Invalid media key")
    if not any(key.startswith(prefix) for prefix in _ALLOWED_KEY_PREFIXES):
        raise ValidationError(message="Media key not allowed")
    return key


@router.post(
    "/upload",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Upload image",
    description=(
        "Upload an image to configured storage (local disk or R2). "
        "Allowed types: jpg, png, webp, gif (max 5 MB)."
    ),
)
async def upload_image(
    file: UploadFile = File(..., description="Image file to upload"),
    product_id: Optional[int] = Form(default=None, description="Optional product ID to associate with"),
    alt_text: Optional[str] = Form(default=None, description="Alt text for the image"),
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    """Upload an image file to storage."""
    content, content_type = await read_upload_file(file)

    if product_id is not None:
        product = await session.get(Product, product_id)
        if product is None:
            raise NotFound(resource_name="Product", resource_id=product_id)

        image = await upload_product_image(
            session,
            product,
            content,
            content_type,
            storage=storage,
            alt_text=alt_text,
        )
        key = storage_key_from_url(image.url) or ""

        return {
            "url": image.url,
            "key": key,
            "image_id": image.id,
            "variants": variant_urls_from_primary_url(image.url),
            "message": "Image uploaded and associated with product",
        }

    payload = await upload_standalone_image(content, content_type, storage=storage)

    return {
        **payload,
        "message": "Image uploaded",
    }


@router.get(
    "/{key:path}",
    summary="Get media URL",
    description="Return a URL to access stored media (presigned for R2, direct for local).",
)
async def get_media_url(
    key: str,
    current_user: CurrentUser = Depends(get_admin_user),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    """Get a URL for a media file."""
    del current_user
    _validate_media_key(key)
    try:
        url = await storage.get_url(key)
    except FileNotFoundError as exc:
        raise NotFound(resource_name="Media", resource_id=key) from exc
    except Exception as exc:
        logger.error("Failed to get URL for key '%s': %s", key, exc)
        raise ValidationError(message="Failed to generate media URL") from exc

    return {
        "url": url,
        "key": key,
        "expires_in": 3600 if settings.storage_backend == "r2" else None,
    }


@router.delete(
    "/{key:path}",
    response_model=dict,
    summary="Delete media",
    description="Delete a media file from storage. Admin only.",
)
async def delete_media(
    key: str,
    current_user: CurrentUser = Depends(get_admin_user),
    session=Depends(get_session),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    """Delete a media file from storage."""
    _validate_media_key(key)
    if "products/" in key:
        result = await session.execute(
            select(ProductImage).where(col(ProductImage.url).contains(key.rsplit("/", 1)[0]))
        )
        images = result.scalars().all()
        for img in images:
            await delete_product_image(session, img, storage=storage)
        if not images:
            for variant_key in variant_keys_from_primary_key(key):
                await storage.delete(variant_key)
    else:
        await storage.delete(key)
    return {"message": f"Media '{key}' deleted"}
