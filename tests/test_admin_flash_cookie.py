"""Tests for admin flash cookie encoding."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import Response

from app.admin.session import FLASH_COOKIE_NAME, read_flash_cookie, set_flash_cookie


def test_set_flash_cookie_accepts_unicode_without_latin1_error():
    response = Response()
    message = "Sync complete — no changes."
    set_flash_cookie(response, message)

    header = response.headers.get("set-cookie", "")
    assert FLASH_COOKIE_NAME in header
    assert "—" not in header


def test_read_flash_cookie_decodes_encoded_value():
    encoded = quote("Sync complete — no changes.", safe="")
    assert read_flash_cookie(encoded) == "Sync complete — no changes."


def test_read_flash_cookie_passes_through_legacy_ascii():
    assert read_flash_cookie("Catalog sync saved") == "Catalog sync saved"
