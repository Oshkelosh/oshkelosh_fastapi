"""Normalize product images into WebP variants at ingest time."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from app.config import settings
from app.core.exceptions import ValidationError

OUTPUT_CONTENT_TYPE = "image/webp"
VARIANT_NAMES = ("full", "card", "thumb")
FULL_VARIANT = "full"
VARIANT_QUALITIES = {"full": 85, "card": 80, "thumb": 75}
MAX_OUTPUT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class ProcessedImage:
    """Processed image group ready for storage upload."""

    group_id: str
    variants: dict[str, tuple[bytes, str]]


def _variant_specs() -> list[tuple[str, int]]:
    return [
        ("full", settings.image_variant_full_max_px),
        ("card", settings.image_variant_card_max_px),
        ("thumb", settings.image_variant_thumb_max_px),
    ]


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


def _encode_webp(image: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=6)
    return buffer.getvalue()


def _encode_variant(image: Image.Image, variant: str) -> bytes:
    quality = VARIANT_QUALITIES[variant]
    data = _encode_webp(image, quality)
    if variant != FULL_VARIANT or len(data) <= MAX_OUTPUT_BYTES:
        return data

    while len(data) > MAX_OUTPUT_BYTES and quality > 50:
        quality -= 5
        data = _encode_webp(image, quality)

    if len(data) > MAX_OUTPUT_BYTES:
        raise ValidationError(message="Processed image exceeds max file size")

    return data


def process_product_image(content: bytes, *, source_content_type: str) -> ProcessedImage:
    """Resize and convert an image into full, card, and thumb WebP variants."""
    if not content:
        raise ValidationError(message="Empty image file")

    base = _flatten_image(_open_image(content, source_content_type))
    group_id = uuid.uuid4().hex
    variants: dict[str, tuple[bytes, str]] = {}

    for name, max_px in _variant_specs():
        resized = _resize_to_max(base, max_px)
        encoded = _encode_variant(resized, name)
        variants[name] = (encoded, OUTPUT_CONTENT_TYPE)

    return ProcessedImage(group_id=group_id, variants=variants)
