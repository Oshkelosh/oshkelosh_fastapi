"""Parse and validate pasted external <script> tags."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

_ALLOWED_BOOL_ATTRS = frozenset({"defer", "async", "nomodule"})
_ALLOWED_STR_ATTRS = frozenset(
    {"type", "crossorigin", "integrity", "referrerpolicy", "charset"}
)


class ScriptTagError(ValueError):
    """Raised when a pasted script tag is invalid."""


class _ScriptTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attrs: dict[str, str | bool] | None = None
        self._open = False
        self._closed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._on_start(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._on_start(tag, attrs)
        self._closed = True
        self._open = False

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script":
            raise ScriptTagError(f"Unexpected closing tag </{tag}>")
        if not self._open and not self._closed:
            raise ScriptTagError("Unexpected </script> without opening tag")
        self._closed = True
        self._open = False

    def handle_data(self, data: str) -> None:
        if data.strip():
            raise ScriptTagError("Inline script content is not allowed")

    def handle_comment(self, data: str) -> None:
        raise ScriptTagError("Comments inside script tags are not allowed")

    def _on_start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            raise ScriptTagError(f"Only a <script> tag is allowed (got <{tag}>)")
        if self.attrs is not None or self._closed:
            raise ScriptTagError("Paste exactly one <script> tag")
        self.attrs = _normalize_attrs(attrs)
        self._open = True


def _normalize_attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str | bool]:
    seen: set[str] = set()
    out: dict[str, str | bool] = {}
    for raw_name, raw_value in attrs:
        name = raw_name.lower().strip()
        if not name:
            continue
        if name in seen:
            raise ScriptTagError(f"Duplicate attribute: {name}")
        seen.add(name)
        if name.startswith("on"):
            raise ScriptTagError(f"Event-handler attribute not allowed: {name}")
        if name == "src":
            if raw_value is None or not str(raw_value).strip():
                raise ScriptTagError("script src is required")
            out["src"] = str(raw_value).strip()
            continue
        if name in _ALLOWED_BOOL_ATTRS:
            # Presence means true; explicit false-ish values rejected.
            if raw_value is not None and raw_value.strip().lower() in {"false", "0", "no"}:
                continue
            out[name] = True
            continue
        if name in _ALLOWED_STR_ATTRS or name.startswith("data-"):
            if raw_value is None:
                out[name] = True
            else:
                out[name] = str(raw_value).strip()
            continue
        raise ScriptTagError(f"Attribute not allowed: {name}")
    return out


def require_https_src(src: str) -> str:
    parsed = urlparse(src)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ScriptTagError("script src must be an https:// URL")
    return src


def parse_script_tag(raw: str) -> tuple[str, dict[str, str | bool]]:
    """Parse one external empty <script> tag into (src, attrs without src)."""
    text = (raw or "").strip()
    if not text:
        raise ScriptTagError("Paste a <script> tag")

    parser = _ScriptTagParser()
    try:
        parser.feed(text)
        parser.close()
    except ScriptTagError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise ScriptTagError(f"Invalid HTML: {exc}") from exc

    if parser.attrs is None or not parser._closed:
        raise ScriptTagError("Paste a complete <script ...></script> tag")

    src_val = parser.attrs.pop("src", None)
    if not isinstance(src_val, str):
        raise ScriptTagError("script src is required")
    src = require_https_src(src_val)
    return src, parser.attrs


def format_script_tag(src: str, attrs: dict[str, Any]) -> str:
    """Rebuild a displayable <script> tag from stored src + attrs."""
    parts = [f'src="{src}"']
    for key, value in attrs.items():
        if value is True:
            parts.append(str(key))
        elif value is False or value is None:
            continue
        else:
            parts.append(f'{key}="{value}"')
    return f"<script {' '.join(parts)}></script>"
