"""Branding asset upload helpers for site logo and favicon."""

from __future__ import annotations

from io import BytesIO
from typing import Literal
from urllib.parse import urlparse

from PIL import Image, ImageOps

from app.config import LOCAL_MEDIA_MOUNT_PATH, settings
from app.core.exceptions import ValidationError
from app.storage import StorageBackend

BrandingKind = Literal["logo", "favicon"]
OUTPUT_CONTENT_TYPE = "image/webp"

_LOGO_MAX_PX = 512
_FAVICON_SIZE_PX = 48
_LOGO_QUALITY = 85
_FAVICON_QUALITY = 80

_BRANDING_KEYS: dict[BrandingKind, str] = {
    "logo": "branding/logo.webp",
    "favicon": "branding/favicon.webp",
}


def branding_storage_key(kind: BrandingKind) -> str:
    """Return the fixed storage key for a branding asset kind."""
    return _BRANDING_KEYS[kind]


def branding_key_from_url(url: str | None) -> str | None:
    """Extract a managed branding storage key from a public media URL."""
    if not url:
        return None

    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if path.startswith(f"{LOCAL_MEDIA_MOUNT_PATH}/"):
        key = path[len(LOCAL_MEDIA_MOUNT_PATH) + 1 :]
        return key if key in _BRANDING_KEYS.values() else None

    if path in _BRANDING_KEYS.values():
        return path

    public = (settings.r2_public_base_url or "").rstrip("/")
    if public and url.startswith(public):
        key = url[len(public) :].lstrip("/")
        return key if key in _BRANDING_KEYS.values() else None

    return None


def _open_image(content: bytes, source_content_type: str) -> Image.Image:
    try:
        image = Image.open(BytesIO(content))
        image.load()
    except Exception as exc:
        raise ValidationError(message="Invalid or corrupt image file") from exc

    if source_content_type == "image/gif":
        try:
            image.seek(0)
        except EOFError as exc:
            raise ValidationError(message="Invalid or empty GIF image") from exc

    return image


def _flatten_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)

    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background

    if image.mode == "P":
        if "transparency" in image.info:
            return _flatten_image(image.convert("RGBA"))
        return image.convert("RGB")

    if image.mode != "RGB":
        return image.convert("RGB")

    return image


def _resize_to_max(image: Image.Image, max_px: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_px:
        return image
    scale = max_px / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _resize_square(image: Image.Image, size_px: int) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    if cropped.size[0] == size_px and cropped.size[1] == size_px:
        return cropped
    return cropped.resize((size_px, size_px), Image.Resampling.LANCZOS)


def _encode_webp(image: Image.Image, *, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=6)
    return buffer.getvalue()


def process_branding_image(
    content: bytes,
    *,
    kind: BrandingKind,
    source_content_type: str,
) -> bytes:
    """Resize and convert a branding image to WebP."""
    if not content:
        raise ValidationError(message="Empty image file")

    base = _flatten_image(_open_image(content, source_content_type))
    if kind == "logo":
        processed = _resize_to_max(base, _LOGO_MAX_PX)
        quality = _LOGO_QUALITY
    else:
        processed = _resize_square(base, _FAVICON_SIZE_PX)
        quality = _FAVICON_QUALITY

    return _encode_webp(processed, quality=quality)


async def delete_branding_asset_if_managed(
    url: str | None,
    *,
    storage: StorageBackend,
) -> None:
    """Delete a prior managed branding file when replacing or clearing."""
    key = branding_key_from_url(url)
    if key:
        await storage.delete(key)


async def upload_branding_asset(
    kind: BrandingKind,
    content: bytes,
    content_type: str,
    *,
    storage: StorageBackend,
) -> str:
    """Process and upload a branding asset; returns its public URL."""
    processed = process_branding_image(
        content,
        kind=kind,
        source_content_type=content_type,
    )
    key = branding_storage_key(kind)
    return await storage.upload(key, processed, OUTPUT_CONTENT_TYPE)
