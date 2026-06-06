"""
Addon registry – auto-discovers and manages addon instances.

Scans ``app/addons/<category>/<addon_name>/`` directories for classes
that inherit from ``BaseAddon``, registers them, and provides
enable/disable / config management.
"""

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List

from sqlmodel import select

from app.addons.base import BaseAddon

logger = logging.getLogger(__name__)

# The directory that contains all addon packages
_ADDONS_DIR = Path(__file__).resolve().parent


class AddonRegistry:
    """Central registry for all discovered addons."""

    def __init__(self) -> None:
        self._registry: Dict[str, BaseAddon] = {}
        self._discovered: List[type] = []

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> List[type]:
        """Walk ``app/addons/<category>/<addon>`` and import each addon module.

        Returns the list of ``BaseAddon`` subclasses found.
        """
        discovered: List[type] = []

        for category_dir in _ADDONS_DIR.iterdir():
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith("_"):
                continue
            for addon_dir in category_dir.iterdir():
                if not addon_dir.is_dir():
                    continue
                if addon_dir.name.startswith("_"):
                    continue

                addon_module = f"app.addons.{category_dir.name}.{addon_dir.name}"
                modules_to_scan: list = []

                try:
                    modules_to_scan.append(importlib.import_module(addon_module))
                except ModuleNotFoundError:
                    logger.debug("Skipping addon (no package): %s", addon_module)
                    continue
                except Exception:
                    logger.exception("Failed to import addon package %s", addon_module)
                    continue

                try:
                    modules_to_scan.append(
                        importlib.import_module(f"{addon_module}.addon")
                    )
                except ModuleNotFoundError:
                    pass
                except Exception:
                    logger.exception("Failed to import addon module %s.addon", addon_module)

                for mod in modules_to_scan:
                    for name, obj in inspect.getmembers(mod, inspect.isclass):
                        if (
                            issubclass(obj, BaseAddon)
                            and obj is not BaseAddon
                            and not inspect.isabstract(obj)
                            and obj.__module__ == mod.__name__
                        ):
                            if obj not in discovered:
                                discovered.append(obj)
                                logger.info(
                                    "Discovered addon %s (%s) – %s",
                                    obj.addon_id,
                                    obj.addon_name,
                                    obj.addon_category,
                                )

        self._discovered = discovered
        return discovered

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, addon_class: type) -> None:
        """Instantiate and register an addon class."""
        if inspect.isabstract(addon_class):
            return
        instance = addon_class()  # type: ignore[call-arg]
        self._registry[instance.addon_id] = instance
        logger.info("Registered addon %s", instance.addon_id)

    def register_all(self) -> None:
        """Register every discovered addon."""
        if not self._discovered:
            self.discover()
        for cls in self._discovered:
            if cls.addon_id not in self._registry:
                self.register(cls)

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def _validate_and_store_config(self, addon: BaseAddon, config: dict) -> dict:
        """Validate config against the addon schema and store on the instance."""
        schema = addon.config_schema()
        validated = schema(**config)
        stored = validated.model_dump(mode="json")
        addon._config = stored  # type: ignore[attr-defined]
        return stored

    async def enable_async(self, addon_id: str, config: dict) -> None:
        """Validate config, enable, and initialize an addon."""
        addon = self._registry.get(addon_id)
        if addon is None:
            raise KeyError(f"Addon '{addon_id}' not found in registry")
        stored = self._validate_and_store_config(addon, config)
        addon.is_enabled = True
        logger.info("Enabling addon '%s' …", addon_id)
        await addon.initialize(stored)

    async def disable_async(self, addon_id: str) -> None:
        """Shut down and disable a registered addon."""
        addon = self._registry.get(addon_id)
        if addon is None:
            raise KeyError(f"Addon '{addon_id}' not found in registry")
        if addon.is_enabled:
            await addon.shutdown()
        addon.is_enabled = False
        logger.info("Disabled addon '%s'", addon_id)

    def enable(self, addon_id: str, config: dict) -> None:
        """Sync alias – prefer ``enable_async`` in async contexts."""
        raise RuntimeError("Use enable_async() from async code")

    def disable(self, addon_id: str) -> None:
        """Sync alias – prefer ``disable_async`` in async contexts."""
        raise RuntimeError("Use disable_async() from async code")

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def get_config(self, addon_id: str) -> dict:
        """Return the current config dict for an addon (or empty dict)."""
        addon = self._registry.get(addon_id)
        if addon is None:
            return {}
        if hasattr(addon, "_config") and addon._config:
            return addon._config
        return {}

    def save_config(self, addon_id: str, config: dict) -> dict:
        """Validate and store configuration for an addon (does not persist to DB)."""
        addon = self._registry.get(addon_id)
        if addon is None:
            raise KeyError(f"Addon '{addon_id}' not found in registry")
        stored = self._validate_and_store_config(addon, config)
        logger.info("Saved config for addon '%s'", addon_id)
        return stored

    async def save_config_async(self, addon_id: str, config: dict) -> dict:
        """Validate, store, and re-initialize if the addon is enabled."""
        stored = self.save_config(addon_id, config)
        addon = self._registry[addon_id]
        if addon.is_enabled:
            await addon.initialize(stored)
        return stored

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load_from_db(self, session: Any) -> None:
        """Load persisted addon state from ``addon_configs`` into the registry."""
        from models.addon_config import AddonConfig

        result = await session.execute(select(AddonConfig))
        rows = result.scalars().all()
        for row in rows:
            addon = self._registry.get(row.addon_id)
            if addon is None:
                logger.warning("Unknown addon_id in DB: %s", row.addon_id)
                continue
            addon.is_enabled = row.is_enabled
            if row.config:
                addon._config = row.config  # type: ignore[attr-defined]

    async def startup(self, session: Any) -> None:
        """Discover, load DB config, and initialize every enabled addon."""
        self.register_all()
        await self.load_from_db(session)
        for addon_id, addon in self._registry.items():
            if addon.is_enabled:
                config = self.get_config(addon_id)
                try:
                    await addon.initialize(config)
                    logger.info("Addon '%s' started", addon_id)
                except Exception:
                    logger.exception("Failed to start addon '%s'", addon_id)

    async def shutdown(self) -> None:
        """Shutdown every enabled addon."""
        for addon_id, addon in list(self._registry.items()):
            if addon.is_enabled:
                try:
                    await addon.shutdown()
                    logger.info("Addon '%s' shut down", addon_id)
                except Exception:
                    logger.exception("Failed to shut down addon '%s'", addon_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, addon_id: str) -> BaseAddon | None:
        """Return an addon by id, or None."""
        return self._registry.get(addon_id)

    def get_enabled(self, category: str) -> List[BaseAddon]:
        """Return all enabled addons in a category."""
        return [
            addon
            for addon in self._registry.values()
            if addon.addon_category == category and addon.is_enabled
        ]

    def list_addons(self) -> List[dict]:
        """Return metadata for every registered addon."""
        self.register_all()
        return [addon.metadata() for addon in self._registry.values()]

    @property
    def addon_ids(self) -> List[str]:
        """Return all registered addon IDs."""
        return list(self._registry.keys())


# Singleton
addon_registry = AddonRegistry()
