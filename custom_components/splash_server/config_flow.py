"""Configure a SPLASH server and edit its settings later."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CannotConnectError, InvalidStatusError, async_get_status, status_url
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

FORM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): vol.All(str, vol.Strip, vol.Length(min=1)),
        vol.Required(CONF_URL): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
        ),
    }
)


class SplashConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup and reconfiguration."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a new server."""
        return await self._async_server_form("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update the settings of an existing server."""
        return await self._async_server_form("reconfigure", user_input)

    async def _async_server_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> config_entries.ConfigFlowResult:
        """Validate settings and save them after a successful request."""
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        errors = {}
        if user_input is not None:
            try:
                endpoint = status_url(user_input[CONF_URL])
                await async_get_status(async_get_clientsession(self.hass), endpoint)
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidStatusError:
                errors["base"] = "invalid_status"
            else:
                # Check after awaiting so simultaneous setup flows cannot add a duplicate.
                if any(
                    existing is not entry and existing.data[CONF_URL] == endpoint
                    for existing in self._async_current_entries()
                ):
                    errors[CONF_URL] = "already_configured"
                else:
                    title = user_input[CONF_NAME]
                    data = {
                        CONF_URL: endpoint,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    }
                    if entry is not None:
                        return self.async_update_reload_and_abort(
                            entry, title=title, data_updates=data
                        )
                    return self.async_create_entry(title=title, data=data)

        suggestions = user_input or (
            {**entry.data, CONF_NAME: entry.title} if entry is not None else {}
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(FORM_SCHEMA, suggestions),
            errors=errors,
        )
