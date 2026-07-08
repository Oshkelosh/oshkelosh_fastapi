"""Resolve enabled SSO providers for the storefront."""

from __future__ import annotations

from app.services.addons import get_sso_addon


def get_public_sso_providers() -> list[dict[str, str]]:
    """Return public SSO provider metadata for storefront bootstrapping."""
    addon = get_sso_addon()
    if addon is None:
        return []
    return addon.list_public_providers()
