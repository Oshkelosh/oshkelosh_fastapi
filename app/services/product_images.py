"""Product image upload, remote import, and lookup helpers."""

from __future__ import annotations

import asyncio

import logging
import mimetypes
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import UploadFile
from sqlmodel import col, select

from app.config import LOCAL_MEDIA_MOUNT_PATH, settings
from app.core.exceptions import ValidationError
from app.services.image_processing import (
    FULL_VARIANT,
    VARIANT_NAMES,
    ProcessedImage,
    process_product_image,
)
from app.storage import StorageBackend
from app.services.product_popularity import compute_popularity_score
from models.product import Product
from models.product_image import ProductImage
from models.product_variant import ProductVariant
from schemas.product import ProductDetailRead, ProductRead, ProductVariantRead
from app.services.product_variants import VARIANT_STATUS_ACTIVE, get_active_variants

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
REMOTE_DOWNLOAD_TIMEOUT = 30.0
FULL_WEBP_SUFFIX = f"/{FULL_VARIANT}.webp"


def validate_image_content_type(content_type: str) -> str:
    """Return file extension for an allowed image content type."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            message=f"Unsupported file type: {content_type}. "
            f"Allowed: {', '.join(ALLOWED_CONTENT_TYPES.keys())}"
        )
    return ALLOWED_CONTENT_TYPES[content_type]


async def read_upload_file(file: UploadFile, *, max_size: int = MAX_FILE_SIZE) -> tuple[bytes, str]:
    """Read and validate an uploaded image file."""
    file_size = 0
    content = b""
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        file_size += len(chunk)
        content += chunk
        if file_size > max_size:
            raise ValidationError(
                message=f"File too large. Max size is {max_size // (1024 * 1024)} MB"
            )

    if file_size == 0:
        raise ValidationError(message="Empty file uploaded")

    content_type = file.content_type or "application/octet-stream"
    validate_image_content_type(content_type)
    return content, content_type


def product_image_group_prefix(group_id: str) -> str:
    """Storage prefix for a logical product image group."""
    return f"products/{group_id}"


def variant_storage_key(group_id: str, variant: str) -> str:
    """Return the storage key for a named variant."""
    return f"{product_image_group_prefix(group_id)}/{variant}.webp"


def variant_urls_from_primary_url(url: str) -> dict[str, str]:
    """Derive card and thumb URLs from the full variant URL."""
    if not url.endswith(FULL_WEBP_SUFFIX):
        return {}
    base = url[: -len(FULL_WEBP_SUFFIX)]
    return {
        "card": f"{base}/card.webp",
        "thumb": f"{base}/thumb.webp",
    }


def variant_keys_from_primary_key(key: str) -> list[str]:
    """Return all variant storage keys for an image group."""
    if not key.endswith(FULL_WEBP_SUFFIX):
        return [key]
    prefix = key[: -len(FULL_WEBP_SUFFIX)]
    return [f"{prefix}/{variant}.webp" for variant in VARIANT_NAMES]


def storage_key_from_url(url: str) -> str | None:
    """Extract the full-variant storage key from a public media URL."""
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if path.startswith(f"{LOCAL_MEDIA_MOUNT_PATH}/"):
        key = path[len(LOCAL_MEDIA_MOUNT_PATH) + 1 :]
        return key if key.startswith("products/") and key.endswith(FULL_WEBP_SUFFIX) else None
    if path.startswith("products/") and path.endswith(FULL_WEBP_SUFFIX):
        return path
    public = (settings.r2_public_base_url or "").rstrip("/")
    if public and url.startswith(public):
        key = url[len(public) :].lstrip("/")
        return key if key.startswith("products/") and key.endswith(FULL_WEBP_SUFFIX) else None
    return None


def _content_type_from_url(url: str) -> str | None:
    path = urlparse(url).path
    guessed, _ = mimetypes.guess_type(path)
    if guessed in ALLOWED_CONTENT_TYPES:
        return guessed
    return None


async def download_remote_image(url: str) -> tuple[bytes, str]:
    """Download a remote image URL with size and type validation."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=REMOTE_DOWNLOAD_TIMEOUT,
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
            if content_type not in ALLOWED_CONTENT_TYPES:
                content_type = _content_type_from_url(url) or content_type
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise ValidationError(message=f"Unsupported remote image type: {content_type}")

            size = 0
            chunks: list[bytes] = []
            async for chunk in response.aiter_bytes(8192):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise ValidationError(message="Remote image exceeds max file size")
                chunks.append(chunk)
            return b"".join(chunks), content_type


async def upload_processed_variants(
    storage: StorageBackend,
    processed: ProcessedImage,
) -> tuple[str, dict[str, str]]:
    """Upload all variants and return the full URL plus sibling variant URLs."""
    prefix = product_image_group_prefix(processed.group_id)
    urls: dict[str, str] = {}
    for name, (content, content_type) in processed.variants.items():
        key = f"{prefix}/{name}.webp"
        urls[name] = await storage.upload(key, content, content_type)
    siblings = {name: url for name, url in urls.items() if name != FULL_VARIANT}
    return urls[FULL_VARIANT], siblings


async def upload_standalone_image(
    content: bytes,
    content_type: str,
    *,
    storage: StorageBackend,
) -> dict[str, Any]:
    """Process and upload an image not tied to a product."""
    processed = await asyncio.to_thread(
        process_product_image, content, source_content_type=content_type
    )
    full_url, variants = await upload_processed_variants(storage, processed)
    key = storage_key_from_url(full_url) or ""
    return {"url": full_url, "key": key, "variants": variants}


async def upload_product_image(
    session: Any,
    product: Product,
    content: bytes,
    content_type: str,
    *,
    storage: StorageBackend,
    alt_text: str | None = None,
    sort_order: int | None = None,
    variant_id: int | None = None,
) -> ProductImage:
    """Process, upload variants, and attach a ProductImage row."""
    processed = await asyncio.to_thread(
        process_product_image, content, source_content_type=content_type
    )
    public_url, _variants = await upload_processed_variants(storage, processed)

    if sort_order is None:
        result = await session.execute(
            select(ProductImage.sort_order)
            .where(col(ProductImage.product_id) == product.id)
            .order_by(col(ProductImage.sort_order).desc())
            .limit(1)
        )
        max_order = result.scalar_one_or_none()
        sort_order = (max_order + 1) if max_order is not None else 0

    image = ProductImage(
        product_id=product.id,
        variant_id=variant_id,
        url=public_url,
        alt_text=alt_text,
        sort_order=sort_order,
    )
    session.add(image)
    await session.flush()
    await session.refresh(image)
    return image


async def import_images_from_urls(
    session: Any,
    product: Product,
    urls: list[str],
    *,
    storage: StorageBackend,
    alt_text: str | None = None,
    alt_texts: list[str] | None = None,
    variant_id: int | None = None,
) -> list[ProductImage]:
    """Download remote URLs and store as product images."""
    pending: list[tuple[str, str | None]] = []
    for index, url in enumerate(urls):
        normalized = (url or "").strip()
        if not normalized:
            continue
        per_image_alt = None
        if alt_texts and index < len(alt_texts):
            candidate = (alt_texts[index] or "").strip()
            if candidate:
                per_image_alt = candidate
        pending.append((normalized, per_image_alt))

    seen: set[str] = set()
    created: list[ProductImage] = []
    sort_order = 0

    for normalized, per_image_alt in pending:
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            content, content_type = await download_remote_image(normalized)
        except Exception as exc:
            logger.warning("Failed to download product image %s: %s", normalized, exc)
            continue

        image = await upload_product_image(
            session,
            product,
            content,
            content_type,
            storage=storage,
            alt_text=per_image_alt or alt_text or product.name,
            sort_order=sort_order,
            variant_id=variant_id,
        )
        created.append(image)
        sort_order += 1

    return created


async def delete_product_image(
    session: Any,
    image: ProductImage,
    *,
    storage: StorageBackend,
) -> None:
    """Delete a product image row and all stored variants."""
    key = storage_key_from_url(image.url)
    await session.delete(image)
    if key:
        for variant_key in variant_keys_from_primary_key(key):
            try:
                await storage.delete(variant_key)
            except Exception as exc:
                logger.warning("Failed to delete storage object %s: %s", variant_key, exc)


async def list_product_images(session: Any, product_id: int) -> list[ProductImage]:
    """Return images for a product ordered by sort_order."""
    result = await session.execute(
        select(ProductImage)
        .where(col(ProductImage.product_id) == product_id)
        .order_by(col(ProductImage.sort_order).asc())
    )
    return list(result.scalars().all())


async def primary_image_urls_for_products(
    session: Any,
    product_ids: list[int],
) -> dict[int, str]:
    """Return the primary thumbnail URL per product id."""
    if not product_ids:
        return {}

    result = await session.execute(
        select(ProductImage)
        .where(col(ProductImage.product_id).in_(product_ids))
        .order_by(col(ProductImage.product_id).asc(), col(ProductImage.sort_order).asc())
    )
    images = result.scalars().all()
    primary: dict[int, str] = {}
    for image in images:
        if image.product_id not in primary:
            variants = variant_urls_from_primary_url(image.url)
            primary[image.product_id] = variants.get("thumb", image.url)
    return primary


def product_image_to_dict(image: ProductImage) -> dict[str, Any]:
    """Serialize a ProductImage row for API consumers."""
    return {
        "id": image.id,
        "url": image.url,
        "variants": variant_urls_from_primary_url(image.url),
        "alt_text": image.alt_text,
        "sort_order": image.sort_order,
        "variant_id": image.variant_id,
    }


async def images_by_product_id(
    session: Any,
    product_ids: list[int],
) -> dict[int, list[ProductImage]]:
    """Return relational images per product id, ordered by sort_order."""
    if not product_ids:
        return {}

    result = await session.execute(
        select(ProductImage)
        .where(col(ProductImage.product_id).in_(product_ids))
        .order_by(col(ProductImage.product_id).asc(), col(ProductImage.sort_order).asc())
    )
    grouped: dict[int, list[ProductImage]] = {}
    for image in result.scalars().all():
        grouped.setdefault(image.product_id, []).append(image)
    return grouped


def effective_images(relational: list[ProductImage]) -> list[dict[str, Any]]:
    """Return canonical ProductImage rows as API image dicts."""
    return [product_image_to_dict(image) for image in relational]


async def build_product_read(session: Any, product: Product) -> ProductRead:
    """Build ProductRead with relational product image metadata."""
    images_map = await images_by_product_id(session, [product.id])
    payload = product.model_dump()
    payload["images"] = effective_images(images_map.get(product.id, []))
    payload["popularity_score"] = compute_popularity_score(
        payload.get("units_sold", 0), product.created_at
    )
    return ProductRead.model_validate(payload)


async def build_product_detail_read(session: Any, product: Product) -> ProductDetailRead:
    """Build ProductDetailRead with variants and images."""
    images_map = await images_by_product_id(session, [product.id])
    all_images = images_map.get(product.id, [])
    result = await session.execute(
        select(ProductVariant).where(col(ProductVariant.product_id) == product.id)
    )
    all_variants = list(result.scalars().all())
    active = get_active_variants(all_variants)

    variant_reads: list[ProductVariantRead] = []
    for variant in active:
        variant_images = [
            product_image_to_dict(img)
            for img in all_images
            if img.variant_id == variant.id
        ]
        payload = variant.model_dump()
        payload["images"] = variant_images
        variant_reads.append(ProductVariantRead.model_validate(payload))

    detail = product.model_dump()
    detail["popularity_score"] = compute_popularity_score(
        detail.get("units_sold", 0), product.created_at
    )
    shared_images = [
        product_image_to_dict(img)
        for img in all_images
        if img.variant_id is None
    ]
    detail["images"] = shared_images if shared_images else effective_images(all_images)
    detail["variants"] = [v.model_dump() for v in variant_reads]
    return ProductDetailRead.model_validate(detail)


async def build_product_reads(session: Any, products: list[Product]) -> list[ProductRead]:
    """Build ProductRead list with batch-loaded relational images."""
    if not products:
        return []

    product_ids = [product.id for product in products if product.id is not None]
    images_map = await images_by_product_id(session, product_ids)
    reads: list[ProductRead] = []
    for product in products:
        payload = product.model_dump()
        payload["images"] = effective_images(images_map.get(product.id, []))
        payload["popularity_score"] = compute_popularity_score(
            payload.get("units_sold", 0), product.created_at
        )
        reads.append(ProductRead.model_validate(payload))
    return reads
