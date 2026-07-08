"""Tests for addon logging helpers."""

from __future__ import annotations

import io

from loguru import logger

from app.addons.base import BaseAddon
from app.addons.log import info, label_for, warning


class _SampleAddon(BaseAddon):
    addon_id = "sample"
    addon_name = "Sample Addon"
    log_label = "Sample"

    @classmethod
    def config_schema(cls):
        from app.addons.base import AddonConfig

        return AddonConfig

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass


def test_label_for_uses_log_label():
    assert label_for(_SampleAddon) == "Sample"


def test_label_for_falls_back_to_addon_name():
    class NoLabelAddon(_SampleAddon):
        log_label = ""

        addon_name = "Fallback Name"

    assert label_for(NoLabelAddon) == "Fallback Name"


def test_info_prefixes_message():
    buffer = io.StringIO()
    handler_id = logger.add(buffer, format="{message}", level="INFO")
    try:
        info("Stripe", "Initialized")
    finally:
        logger.remove(handler_id)
    assert "[Stripe] Initialized" in buffer.getvalue()


def test_warning_prefixes_message():
    buffer = io.StringIO()
    handler_id = logger.add(buffer, format="{message}", level="WARNING")
    try:
        warning("Printful", "create_order error: {}", "timeout")
    finally:
        logger.remove(handler_id)
    assert "[Printful] create_order error: timeout" in buffer.getvalue()
