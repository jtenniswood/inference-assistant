"""Poll one SPLASH server for all of its entities."""

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnectError, InvalidStatusError, async_get_status
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SplashCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage periodic updates for one server."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up the shared connection and the server's device identity."""
        self.endpoint = entry.data[CONF_URL]
        self.session = async_get_clientsession(hass)
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="SPLASH",
            model="AI LLM Server",
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Read the latest server statistics."""
        try:
            return await async_get_status(self.session, self.endpoint)
        except (CannotConnectError, InvalidStatusError) as err:
            raise UpdateFailed(str(err)) from err


type SplashConfigEntry = ConfigEntry[SplashCoordinator]
