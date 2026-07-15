"""Unit tests for the manual supplier addon."""

from app.addons.suppliers.manual.addon import ManualSupplierAddon


def test_manual_addon_has_required_attrs():
    assert ManualSupplierAddon.addon_id == "manual"
    assert ManualSupplierAddon.addon_category == "supplier"
