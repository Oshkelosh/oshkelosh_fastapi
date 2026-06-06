"""Slug generation utility."""

import re
import unicodedata


def slugify(text: str) -> str:
    """Convert a string to a URL-friendly slug.

    Examples:
        slugify("Hello World!") -> "hello-world"
        slugify("Oshkelosh 101") -> "oshkelosh-101"
        slugify("café résumé") -> "cafe-resume"
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")
