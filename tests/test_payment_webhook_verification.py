"""Payment webhook signature verification and fail-closed default."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.addons.payments.base import PaymentAddon
from app.addons.payments.helpers import (
    verify_hmac_sha256_hex,
    verify_paid_via_refetch,
    verify_stripe_signature,
)


def test_verify_hmac_sha256_hex_accepts_valid_and_rejects_forged():
    secret = "whsec_test"
    body = b'{"id":"evt_1"}'
    good = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_hmac_sha256_hex(secret, body, good) is True
    assert verify_hmac_sha256_hex(secret, body, "deadbeef") is False
    assert verify_hmac_sha256_hex(secret, body, "") is False
    assert verify_hmac_sha256_hex("", body, good) is False


def test_verify_hmac_prefix_binds_timestamp():
    secret = "whsec_test"
    body = b"{}"
    ts = b"1700000000"
    good = hmac.new(secret.encode(), ts + body, hashlib.sha256).hexdigest()
    assert verify_hmac_sha256_hex(secret, body, good, prefix=ts) is True
    # Same signature without the timestamp prefix must not verify.
    assert verify_hmac_sha256_hex(secret, body, good) is False


def test_verify_stripe_signature_roundtrip():
    secret = "whsec_stripe"
    body = b'{"id":"evt_stripe"}'
    ts = "1700000000"
    signed = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig}"
    assert verify_stripe_signature(secret, body, header) is True
    assert verify_stripe_signature(secret, body, f"t={ts},v1=bad") is False
    assert verify_stripe_signature(secret, body, "") is False


@pytest.mark.asyncio
async def test_base_payment_addon_verify_fails_closed():
    class _Bare(PaymentAddon):
        addon_id = "bare"
        addon_name = "Bare"
        version = "1.0.0"

        @classmethod
        def config_schema(cls):
            from pydantic import BaseModel

            return BaseModel

        async def initialize(self, config):
            return None

        async def shutdown(self):
            return None

        async def create_payment(self, *a, **k):
            return {}

        async def confirm_payment(self, payment_id):
            return {}

        async def refund_payment(self, payment_id, amount):
            return {}

        async def get_payment_status(self, payment_id):
            return {}

        async def parse_webhook(self, payload, signature):
            from schemas.payment import PaymentWebhookOutcome

            return PaymentWebhookOutcome(handled=True)

    addon = _Bare()
    assert await addon.verify_webhook(headers={}, body=b"{}") is False


@pytest.mark.asyncio
async def test_verify_paid_via_refetch_requires_paid_status():
    async def fetch_paid(pid):
        return {"status": "paid"}

    async def fetch_open(pid):
        return {"status": "open"}

    async def fetch_error(pid):
        raise RuntimeError("network")

    assert await verify_paid_via_refetch(fetch_paid, "tr_1", {"paid"}) is True
    assert await verify_paid_via_refetch(fetch_open, "tr_1", {"paid"}) is False
    assert await verify_paid_via_refetch(fetch_error, "tr_1", {"paid"}) is False
    assert await verify_paid_via_refetch(fetch_paid, "", {"paid"}) is False
