"""Structured logging helpers for addon packages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from app.addons.base import BaseAddon


def label_for(addon: BaseAddon | type[BaseAddon]) -> str:
    """Return the log prefix label for an addon instance or class."""
    cls = addon if isinstance(addon, type) else type(addon)
    label = getattr(cls, "log_label", "") or getattr(cls, "addon_name", "addon")
    return str(label)


def _tag(label: str) -> str:
    return f"[{label}]"


def info(label: str, message: str, *args: object) -> None:
    logger.info(f"{_tag(label)} {message}", *args)


def warning(label: str, message: str, *args: object) -> None:
    logger.warning(f"{_tag(label)} {message}", *args)


def exception(label: str, message: str, *args: object) -> None:
    logger.exception(f"{_tag(label)} {message}", *args)
