"""Media upload endpoints (local filesystem or Cloudflare R2)."""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlmodel import col, select

from app.config import settings
from app.core.dependencies import CurrentUser, get_admin_user, get_current_user
from app.core.exceptions import NotFound, ValidationError
from app.db.connection import get_session
from app.storage import StorageBackend, get_storage
from models.product import Product
from models.product_image import ProductImage

router = APIRouter(prefix="/media", tags=["media"])

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

_ALLOWED_KEY_PREFIXES = ("products/", "media/")


def _validate_media_key(key: str) -> str:
    """Reject path traversal and restrict to known storage prefixes."""
    if ".." in key or key.startswith("/"):
        raise ValidationError(message="Invalid media key")
    if not any(key.startswith(prefix) for prefix in _ALLOWED_KEY_PREFIXES):
        raise ValidationError(message="Media key not allowed")
    return key


def _validate_file(file: UploadFile) -> str:
    """Validate an uploaded file. Returns a unique filename with extension."""
    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            message=f"Unsupported file type: {content_type}. "
            f"Allowed: {', '.join(ALLOWED_CONTENT_TYPES.keys())}"
        )
    ext = ALLOWED_CONTENT_TYPES[content_type]
    return f"{uuid.uuid4().hex}{ext}"


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
    file_size = 0
    content = b""
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        file_size += len(chunk)
        content += chunk
        if file_size > MAX_FILE_SIZE:
            raise ValidationError(
                message=f"File too large. Max size is {MAX_FILE_SIZE // (1024 * 1024)} MB"
            )

    if file_size == 0:
        raise ValidationError(message="Empty file uploaded")

    unique_name = _validate_file(file)
    key = f"products/{unique_name}"

    public_url = await storage.upload(
        key,
        content,
        file.content_type or "application/octet-stream",
    )

    if product_id is not None:
        product = await session.get(Product, product_id)
        if product is None:
            raise NotFound(resource_name="Product", resource_id=product_id)

        image = ProductImage(
            product_id=product_id,
            url=public_url,
            alt_text=alt_text,
        )
        session.add(image)
        await session.flush()
        await session.refresh(image)

        return {
            "url": public_url,
            "key": key,
            "image_id": image.id,
            "message": "Image uploaded and associated with product",
        }

    return {
        "url": public_url,
        "key": key,
        "message": "Image uploaded",
    }


@router.get(
    "/{key:path}",
    summary="Get media URL",
    description="Return a URL to access stored media (presigned for R2, direct for local).",
)
async def get_media_url(
    key: str,
    current_user: CurrentUser = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    """Get a URL for a media file."""
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
    if "products/" in key:
        result = await session.execute(
            select(ProductImage).where(col(ProductImage.url).contains(key))
        )
        images = result.scalars().all()
        for img in images:
            await session.delete(img)

    await storage.delete(key)
    return {"message": f"Media '{key}' deleted"}
