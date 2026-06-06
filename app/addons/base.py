"""
Base classes for the Oshkelosh addon architecture.

Provides AddonConfig (Pydantic model) and BaseAddon (ABC) that every
addon must inherit from.
"""

from abc import ABC, abstractmethod
from typing import List, Type

from fastapi import APIRouter
from pydantic import BaseModel


class AddonConfig(BaseModel):
    """Base configuration model for all addons.

    Subclasses should define their own fields as needed.
    Use ``Field(...)``, ``SecretStr``, ``Field(default=...)`` etc.
    """

    class Config:
        extra = "forbid"


class BaseAddon(ABC):
    """Abstract base class that every addon must implement.

    Attributes:
        addon_id:       Unique string identifier, e.g. ``"printful"``.
        addon_name:     Human-readable display name.
        addon_description: Brief description shown in the admin UI.
        addon_category: One of ``"supplier"``, ``"payment"``, ``"notification"``,
            ``"frontend"``, or ``"tool"``.
        version:        Semantic version string.
        is_enabled:     Runtime flag (set by ``AddonRegistry``).
    """

    addon_id: str = "base"
    addon_name: str = "Base Addon"
    addon_description: str = ""
    addon_category: str = "supplier"
    version: str = "0.1.0"
    is_enabled: bool = False

    @classmethod
    @abstractmethod
    def config_schema(cls) -> Type["AddonConfig"]:
        """Return the Pydantic config model for this addon."""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Called when the addon is enabled.

        Args:
            config: Validated configuration dict (instance of the addon's config schema).
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup resources when the addon is disabled or the app shuts down."""
        ...

    def get_routers(self) -> List[APIRouter]:
        """Return API routers contributed by this addon (mounted at ``/api/v1/...``)."""
        return []

    def get_admin_routes(self) -> List[APIRouter]:
        """Return admin sub-routes (mounted at ``/admin/...``)."""
        return []

    def get_admin_templates(self) -> str:
        """Return the file-system path to this addon's Jinja2 template directory."""
        return ""

    def get_admin_static(self) -> str:
        """Return the file-system path to this addon's static assets."""
        return ""

    def api_mount_prefix(self) -> str:
        """URL prefix for public API routers (under ``/api/v1``)."""
        return f"/{self.addon_category}s/{self.addon_id}"

    def admin_mount_prefix(self) -> str:
        """URL prefix for admin routers (under ``/admin``)."""
        return f"/{self.addon_category}s/{self.addon_id}"

    def metadata(self) -> dict:
        """Return a metadata dict for list_addons()."""
        return {
            "addon_id": self.addon_id,
            "addon_name": self.addon_name,
            "addon_description": self.addon_description,
            "addon_category": self.addon_category,
            "version": self.version,
            "is_enabled": self.is_enabled,
            "config_schema": self.config_schema().__name__,
            "has_admin_routes": bool(self.get_admin_routes()),
            "configure_url": self._configure_url(),
        }

    def _configure_url(self) -> str:
        """Admin URL for configuring this addon."""
        if self.get_admin_routes():
            return f"/admin{self.admin_mount_prefix()}"
        return f"/admin/addons/{self.addon_id}/configure"
