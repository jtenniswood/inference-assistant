"""Inference Assistant for Home Assistant."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import InferenceConfigEntry, InferenceCoordinator

PLATFORMS = (Platform.BINARY_SENSOR, Platform.SENSOR)


async def async_setup_entry(hass: HomeAssistant, entry: InferenceConfigEntry) -> bool:
    """Set up one SPLASH server."""
    coordinator = InferenceCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InferenceConfigEntry) -> bool:
    """Unload one SPLASH server."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
