"""Discover, configure, and reconfigure a SPLASH server."""

from asyncio import Task
from ipaddress import IPv4Address
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_URL
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from yarl import URL

from .api import CannotConnectError, InvalidStatusError, async_get_status, status_url
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .discovery import async_discover, async_probe, instance_id

CONFIRM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): vol.All(str, vol.Strip, vol.Length(min=1)),
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
        ),
    }
)
FORM_SCHEMA = CONFIRM_SCHEMA.extend({vol.Required(CONF_URL): str})


class SplashConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle discovery, initial setup, and reconfiguration."""

    _scan: Task[dict[str, dict[str, Any]]] | None = None
    _discovered_url: str
    _discovered_name: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose how to find a server."""
        return self.async_show_menu(step_id="user", menu_options=["discover", "manual"])

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a server by its known address."""
        return await self._async_server_form("manual", user_input)

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Run a single local scan while showing progress."""
        if self._scan is None:
            self._scan = self.hass.async_create_background_task(
                async_discover(self.hass), "Discover SPLASH servers"
            )
        if self._scan.done():
            return self.async_show_progress_done(next_step_id="select_server")
        return self.async_show_progress(
            step_id="discover", progress_action="discover", progress_task=self._scan
        )

    async def async_step_select_server(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user select an unconfigured result from the scan."""
        assert self._scan is not None
        servers = {
            endpoint: f"SPLASH ({URL(endpoint).host})"
            for endpoint, status in self._scan.result().items()
            if not self._is_configured(endpoint, status)
        }
        if user_input is not None and (endpoint := user_input[CONF_URL]) in servers:
            self._discovered_url = endpoint
            self._discovered_name = servers[endpoint]
            return await self.async_step_confirm()

        if not servers:
            self._scan = None
            return await self.async_step_no_servers()

        return self.async_show_form(
            step_id="select_server",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": endpoint, "label": label}
                                for endpoint, label in servers.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors={CONF_URL: "already_configured"} if user_input is not None else {},
        )

    async def async_step_no_servers(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Offer another scan or manual setup when the scan found no new servers."""
        return self.async_show_menu(
            step_id="no_servers", menu_options=["discover", "manual"]
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Verify a Splash Bonjour announcement before offering setup."""
        if not discovery_info.port:
            return self.async_abort(reason="invalid_status")

        # Splash normally listens on IPv4, although the Mac can advertise IPv6 too.
        for ip in sorted(
            discovery_info.ip_addresses, key=lambda ip: not isinstance(ip, IPv4Address)
        ):
            if ip.is_global or ip.is_multicast or ip.is_loopback or ip.is_unspecified:
                continue
            endpoint = str(
                URL.build(
                    scheme="http",
                    host=str(ip),
                    port=discovery_info.port,
                    path="/status",
                )
            )
            if (status := await async_probe(self.hass, endpoint)) is not None:
                break
        else:
            return self.async_abort(reason="invalid_status")

        if self._is_configured(endpoint, status):
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(discovery_info.name.casefold())
        self._abort_if_unique_id_configured()
        self._discovered_url = endpoint
        self._discovered_name = discovery_info.name.removesuffix(
            f".{discovery_info.type}"
        )
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm and name a discovered server."""
        return await self._async_server_form("confirm", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update the settings of an existing server."""
        return await self._async_server_form("reconfigure", user_input)

    def _is_configured(
        self,
        endpoint: str,
        status: dict[str, Any],
        *,
        exclude: config_entries.ConfigEntry | None = None,
    ) -> bool:
        """Match an existing URL or an alternate address for the same process."""
        identity = instance_id(status)
        for existing in self._async_current_entries(include_ignore=False):
            if existing is exclude:
                continue
            if existing.data.get(CONF_URL) == endpoint:
                return True
            coordinator = getattr(existing, "runtime_data", None)
            if (
                existing.state is config_entries.ConfigEntryState.LOADED
                and coordinator is not None
                and coordinator.last_update_success
                and identity is not None
                and instance_id(coordinator.data) == identity
            ):
                return True
        return False

    async def _async_server_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> config_entries.ConfigFlowResult:
        """Validate settings and save them after a successful request."""
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        confirming = step_id == "confirm"
        errors = {}
        if user_input is not None:
            try:
                endpoint = (
                    self._discovered_url
                    if confirming
                    else status_url(user_input[CONF_URL])
                )
                status = await async_get_status(
                    async_get_clientsession(self.hass), endpoint
                )
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except InvalidStatusError:
                errors["base"] = "invalid_status"
            else:
                if self._is_configured(endpoint, status, exclude=entry):
                    errors["base" if confirming else CONF_URL] = "already_configured"
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

        suggestions = {}
        if entry is not None:
            suggestions = {**entry.data, CONF_NAME: entry.title}
        if confirming:
            suggestions = {CONF_NAME: self._discovered_name}
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                CONFIRM_SCHEMA if confirming else FORM_SCHEMA, user_input or suggestions
            ),
            description_placeholders={"url": self._discovered_url}
            if confirming
            else None,
            errors=errors,
        )
