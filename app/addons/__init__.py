"""
Oshkelosh Addon system – auto-discovers and loads every addon.

Importing this module triggers discovery and registration of all
add-on packages located under ``app/addons/``.

Exports:
    addon_registry – the global ``AddonRegistry`` singleton.
    AddonRegistry  – the registry class (re-export for convenience).
    BaseAddon      – abstract base class (re-export for convenience).
"""

from app.addons.base import BaseAddon
from app.addons.registry import AddonRegistry, addon_registry

# Auto-discover and register addons on import
addon_registry.discover()
addon_registry.register_all()

__all__ = ["addon_registry", "AddonRegistry", "BaseAddon"]
