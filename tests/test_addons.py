"""Tests for the addon registry and base interfaces."""

import pytest

from app.addons.base import BaseAddon


class TestBaseAddon:
    """Test the abstract base addon interface."""

    def test_base_addon_requires_subclass(self):
        """BaseAddon should be abstract and not instantiable directly."""
        with pytest.raises(TypeError):
            BaseAddon()


class TestPrintfulAddon:
    """Test the Printful supplier addon."""

    def test_printful_addon_has_required_attrs(self):
        """Printful addon should have all required class attributes."""
        from app.addons.suppliers.printful.addon import PrintfulAddon
        assert hasattr(PrintfulAddon, "addon_id")
        assert hasattr(PrintfulAddon, "addon_name")
        assert hasattr(PrintfulAddon, "addon_description")
        assert hasattr(PrintfulAddon, "addon_category")
        assert hasattr(PrintfulAddon, "config_schema")
        assert PrintfulAddon.addon_id == "printful"
        assert PrintfulAddon.addon_category == "supplier"

    def test_printful_config_schema(self):
        """Printful config schema should validate correctly."""
        from app.addons.suppliers.printful.addon import PrintfulConfig
        config = PrintfulConfig(api_key="test-key", api_username="test-user")
        assert config.api_key.get_secret_value() == "test-key"
        assert config.api_username == "test-user"

    def test_printful_config_requires_api_key(self):
        """Printful config should require api_key."""
        from app.addons.suppliers.printful.addon import PrintfulConfig
        with pytest.raises(Exception):
            PrintfulConfig()  # Missing required fields


class TestStripeAddon:
    """Test the Stripe payment addon."""

    def test_stripe_addon_has_required_attrs(self):
        """Stripe addon should have all required class attributes."""
        from app.addons.payments.stripe.addon import StripeAddon
        assert StripeAddon.addon_id == "stripe"
        assert StripeAddon.addon_category == "payment"

    def test_stripe_config_schema(self):
        """Stripe config schema should validate correctly."""
        from app.addons.payments.stripe.addon import StripeConfig
        config = StripeConfig(
            secret_key="sk_test_abc",
            publishable_key="pk_test_abc",
            webhook_secret="whsec_test",
        )
        assert config.secret_key.get_secret_value() == "sk_test_abc"


class TestEmailAddon:
    """Test the email notification addon."""

    def test_email_addon_has_required_attrs(self):
        """Email addon should have all required class attributes."""
        from app.addons.notifications.email.addon import EmailPostmarkAddon
        assert EmailPostmarkAddon.addon_id == "email_postmark"
        assert EmailPostmarkAddon.addon_category == "notification"


class TestAddonRegistry:
    """Test the addon registry."""

    def test_registry_discover_addons(self):
        """Registry should discover all installed addons."""
        from app.addons.registry import AddonRegistry
        registry = AddonRegistry()
        addons = registry.list_addons()
        addon_ids = [a["addon_id"] for a in addons]
        assert "printful" in addon_ids
        assert "stripe" in addon_ids
        assert "email_postmark" in addon_ids

    def test_registry_get_enabled_by_category(self):
        """get_enabled returns only enabled addons in a category."""
        from app.addons.registry import AddonRegistry
        from app.addons.payments.stripe.addon import StripeAddon

        registry = AddonRegistry()
        registry.register(StripeAddon)
        stripe = registry.get("stripe")
        assert stripe is not None
        stripe.is_enabled = True
        enabled = registry.get_enabled("payment")
        assert len(enabled) == 1
        assert enabled[0].addon_id == "stripe"
        stripe.is_enabled = False

    def test_metadata_includes_configure_url(self):
        """Addon metadata should expose admin configure URL."""
        from app.addons.payments.stripe.addon import StripeAddon

        meta = StripeAddon().metadata()
        assert meta["configure_url"] == "/admin/payments/stripe"
        assert meta["has_admin_routes"] is True
