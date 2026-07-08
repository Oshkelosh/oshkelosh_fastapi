"""Addon compatibility checks against the host application."""

from __future__ import annotations

from packaging.version import Version

from app.addons.base import BaseAddon
from app.core.exceptions import ValidationError


def check_min_host_version(addon: BaseAddon, host_version: str) -> None:
    """Refuse enable when the host application is older than the addon requires."""
    minimum = Version(addon.min_host_version)
    host = Version(host_version)
    if host < minimum:
        raise ValidationError(
            message=(
                f"Addon '{addon.addon_id}' requires Oshkelosh {addon.min_host_version} "
                f"or newer (host is {host_version})"
            )
        )
