"""Supplier shared packing-slip / gift-message branding."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.site_settings import packing_slip_from_site_settings
from models.site_settings import SiteSettings


def test_packing_slip_from_site_settings():
    site = SiteSettings(
        store_name="Acme",
        logo_url="https://cdn.example.com/logo.png",
        support_email="hi@acme.test",
        packing_slip_phone="+15551212",
        packing_slip_message="Thanks for shopping!",
    )
    slip = packing_slip_from_site_settings(site)
    assert slip == {
        "store_name": "Acme",
        "logo_url": "https://cdn.example.com/logo.png",
        "email": "hi@acme.test",
        "phone": "+15551212",
        "message": "Thanks for shopping!",
    }


@pytest.mark.asyncio
async def test_fulfillment_passes_gift_and_packing_slip(db_session):
    from app.services.fulfillment import fulfill_order_with_suppliers
    from models.order import Order
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_variant import ProductVariant

    product = Product(
        name="Tee",
        slug="tee-branding",
        price_cents=1000,
        inventory_quantity=5,
        status="published",
    )
    db_session.add(product)
    await db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        title="Default",
        position=0,
        price_cents=1000,
        inventory_quantity=5,
        sku="TEE-1",
        status="active",
        supplier_addon_id="printful",
        supplier_product_id="111",
    )
    db_session.add(variant)
    await db_session.flush()

    order = Order(
        status="paid",
        total_cents=1000,
        tax_cents=0,
        shipping_cents=0,
        currency="usd",
        shipping_address={"line1": "1 Main", "city": "Austin", "zip": "78701", "country": "US"},
        gift_message="Congrats!",
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        variant_id=variant.id,
        product_name="Tee",
        product_sku="TEE-1",
        quantity=1,
        unit_price_cents=1000,
        total_price_cents=1000,
    )
    db_session.add(item)
    await db_session.flush()

    create = AsyncMock(return_value={"success": True, "order_id": "pf-9"})

    class FakeAddon:
        addon_id = "printful"
        is_enabled = True
        create_order = create

    site = SiteSettings(
        store_name="Shop",
        packing_slip_message="Thanks",
        support_email="shop@test",
    )

    with (
        patch("app.services.fulfillment.get_supplier_addon", return_value=FakeAddon()),
        patch(
            "app.services.site_settings.get_site_settings",
            new=AsyncMock(return_value=site),
        ),
    ):
        await fulfill_order_with_suppliers(db_session, order, [item])

    assert create.await_count == 1
    assert create.await_args.kwargs["gift_message"] == "Congrats!"
    assert create.await_args.kwargs["packing_slip"]["store_name"] == "Shop"
    assert create.await_args.kwargs["packing_slip"]["message"] == "Thanks"


@pytest.mark.asyncio
async def test_prodigi_create_order_includes_branding():
    from app.addons.suppliers.prodigi.addon import ProdigiAddon

    addon = ProdigiAddon()
    addon._config = {
        "branding_postcard_url": "https://cdn.example.com/card.jpg",
        "branding_flyer_url": "https://cdn.example.com/flyer.pdf",
    }
    addon._client = AsyncMock()
    addon._client.create_order = AsyncMock(
        return_value={"order": {"id": "ord_1", "status": {"stage": "InProgress"}}}
    )
    result = await addon.create_order(
        [{"supplier_product_id": "SKU-1", "quantity": 1}],
        {"line1": "1 Main", "city": "Austin", "zip": "78701", "country": "US", "first_name": "A", "last_name": "B"},
    )
    assert result["success"] is True
    payload = addon._client.create_order.await_args.args[0]
    assert payload["branding"]["postcard"]["url"] == "https://cdn.example.com/card.jpg"
    assert payload["branding"]["flyer"]["url"] == "https://cdn.example.com/flyer.pdf"


@pytest.mark.asyncio
async def test_gelato_create_order_appends_insert_and_label():
    from app.addons.suppliers.gelato.addon import GelatoAddon

    addon = GelatoAddon()
    addon._config = {
        "auto_submit": True,
        "default_currency": "USD",
        "branded_insert_product_uid": "insert-uid",
        "branded_label_product_uid": "label-uid",
    }
    addon._client = AsyncMock()
    addon._client.create_order = AsyncMock(return_value={"id": "g-1", "status": "created"})
    result = await addon.create_order(
        [{"supplier_product_id": "prod-uid", "quantity": 2}],
        {
            "first_name": "A",
            "last_name": "B",
            "line1": "1 Main",
            "city": "Austin",
            "zip": "78701",
            "country": "US",
            "email": "a@b.test",
        },
        external_id="99",
    )
    assert result["success"] is True
    items = addon._client.create_order.await_args.args[0]["items"]
    uids = [row["productUid"] for row in items]
    assert uids == ["prod-uid", "insert-uid", "label-uid"]
    assert all(row["quantity"] == 1 for row in items[1:])


@pytest.mark.asyncio
async def test_gooten_create_order_adds_necktag():
    from app.addons.suppliers.gooten.addon import GootenAddon

    addon = GootenAddon()
    addon._config = {
        "default_ship_type": "Standard",
        "necktag_image_url": "https://cdn.example.com/neck.png",
    }
    addon._client = AsyncMock()
    addon._client.create_order = AsyncMock(return_value={"OrderId": "go-1"})
    result = await addon.create_order(
        [{"supplier_product_id": "SKU-9", "quantity": 1}],
        {"line1": "1 Main", "city": "NY", "zip": "10001", "country": "US"},
    )
    assert result["success"] is True
    item = addon._client.create_order.await_args.args[0]["Items"][0]
    assert item["AddOns"]["necktag_image_url"] == "https://cdn.example.com/neck.png"


@pytest.mark.asyncio
async def test_cj_create_order_sets_remark_from_gift():
    from app.addons.suppliers.cjdropshipping.addon import CJDropshippingAddon

    addon = CJDropshippingAddon()
    addon._client = AsyncMock()
    addon._client.create_order = AsyncMock(return_value={"orderId": "cj-1"})
    addon._sync_tokens_to_config = MagicMock()
    addon.export_config_updates = MagicMock(return_value={})
    result = await addon.create_order(
        [{"supplier_product_id": "p1", "supplier_variant_id": "v1", "quantity": 1}],
        {
            "first_name": "A",
            "last_name": "B",
            "line1": "1 Main",
            "city": "LA",
            "zip": "90001",
            "country": "US",
            "phone": "555",
        },
        gift_message="Please wrap carefully",
    )
    assert result["success"] is True
    assert addon._client.create_order.await_args.args[0]["remark"] == "Please wrap carefully"
    assert addon.supports_gift_message() is True


@pytest.mark.asyncio
async def test_manual_create_order_includes_gift_message():
    from app.addons.suppliers.manual.addon import ManualSupplierAddon

    supplier = MagicMock()
    supplier.slug = "local"
    supplier.name = "Local"
    supplier.contact_email = None
    supplier.contact_phone = None
    supplier.notes = None
    supplier.is_active = True

    session = AsyncMock()
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.db.connection.session_scope", return_value=session_cm),
        patch(
            "app.services.manual_suppliers.get_manual_supplier",
            new=AsyncMock(return_value=supplier),
        ),
    ):
        result = await ManualSupplierAddon().create_order(
            [{"supplier_product_id": "SKU", "quantity": 1}],
            {"line1": "1 Main"},
            supplier_ref="local",
            gift_message="Happy day",
        )
    assert result["success"] is True
    assert result["gift_message"] == "Happy day"
    assert ManualSupplierAddon().supports_gift_message() is True


def test_order_create_schema_accepts_gift_message():
    from schemas.order import OrderCreateFromCart

    body = OrderCreateFromCart(gift_message="Hello")
    assert body.gift_message == "Hello"


def test_site_settings_public_exposes_gift_flags():
    from schemas.storefront import SiteSettingsPublic

    public = SiteSettingsPublic(
        store_name="Shop",
        gift_messages_enabled=True,
        gift_message_max_length=120,
    )
    assert public.gift_messages_enabled is True
    assert public.gift_message_max_length == 120
