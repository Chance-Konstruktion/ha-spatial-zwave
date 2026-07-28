"""Z-Wave on the floor plan. Does nothing at all without the hub."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .floorplan import async_setup_floorplan


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_setup_floorplan(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Everything this integration holds was registered through
    # entry.async_on_unload, so there is genuinely nothing to undo here.
    return True
