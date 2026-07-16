"""Tests for ISO country normalization."""

import pytest
from pydantic import ValidationError

from app.services.countries import normalize_country_code, require_iso_country
from app.services.pricing.tax_rules import normalize_country
from schemas.address import Address


def test_normalize_country_code_accepts_alpha2_and_aliases():
    assert normalize_country_code("us") == "US"
    assert normalize_country_code("USA") == "US"
    assert normalize_country_code("United States") == "US"
    assert normalize_country_code("United Kingdom") == "GB"
    assert normalize_country_code("UK") == "GB"
    assert normalize_country_code("") is None
    assert normalize_country_code("Narnia") is None


def test_address_schema_normalizes_country():
    addr = Address(
        line1="1 Main",
        city="Austin",
        postal_code="78701",
        country="United States of America",
    )
    assert addr.country == "US"


def test_address_schema_rejects_unknown_country():
    with pytest.raises(ValidationError):
        Address(
            line1="1 Main",
            city="Austin",
            postal_code="78701",
            country="Narnia",
        )


def test_tax_rules_normalize_country_uses_iso():
    assert normalize_country({"country": "usa"}) == "US"
    assert normalize_country({"country_code": "ca"}) == "CA"


def test_require_iso_country_raises():
    with pytest.raises(ValueError):
        require_iso_country("not-a-country")
