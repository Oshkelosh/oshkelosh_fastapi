"""Tests for shop currency helpers and soft preference resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.currency import (
    PREFERRED_CURRENCY_COOKIE,
    client_country_from_request,
    cookie_currency_preference,
    currency_for_country,
    normalize_currency,
    order_currency_code,
    preferred_currency_hint,
)


def test_normalize_currency_uppercases_and_validates():
    assert normalize_currency("eur") == "EUR"
    assert normalize_currency("nope", default="USD") == "USD"
    assert normalize_currency("FOO") == "USD"
    assert normalize_currency(None) == "USD"


def test_currency_for_country():
    assert currency_for_country("DE") == "EUR"
    assert currency_for_country("us") == "USD"
    assert currency_for_country("ZZ") is None


def test_preferred_currency_hint_priority():
    assert (
        preferred_currency_hint(
            shop_currency="USD",
            address_country="DE",
            ip_country="US",
            cookie_preference="GBP",
        )
        == "EUR"
    )
    assert (
        preferred_currency_hint(
            shop_currency="USD",
            ip_country="GB",
            cookie_preference="JPY",
        )
        == "JPY"
    )
    assert preferred_currency_hint(shop_currency="USD", ip_country="GB") == "GBP"
    assert preferred_currency_hint(shop_currency="USD") == "USD"


def test_order_currency_code_lowercases():
    assert order_currency_code("EUR") == "eur"


def test_client_country_from_cf_header():
    request = MagicMock()
    request.headers = {"cf-ipcountry": "de"}
    assert client_country_from_request(request) == "DE"

    request.headers = {"cf-ipcountry": "XX"}
    assert client_country_from_request(request) is None


def test_cookie_currency_preference():
    request = MagicMock()
    request.cookies = {PREFERRED_CURRENCY_COOKIE: "eur"}
    assert cookie_currency_preference(request) == "EUR"

    request.cookies = {PREFERRED_CURRENCY_COOKIE: "NOPE"}
    assert cookie_currency_preference(request) is None
