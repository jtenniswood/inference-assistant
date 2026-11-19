"""Configure an LLM server and edit its settings later."""

from asyncio import Task
from ipaddress import IPv4Address
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_MODEL, CONF_NAME, CONF_URL
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from yarl import URL

from .api import CannotConnectError, InvalidStatusError, monitoring_url
from .backends import (
    BACKENDS,
    CONF_CLEAR_API_KEY,
    CONF_SERVER_TYPE,
    AuthenticationError,
    MetricsUnavailableError,
    ServerType,
    async_fetch_status,
)
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


class InferenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup and reconfiguration."""

    _server_type = ServerType.SPLASH
    _scan: Task[dict[str, dict[str, Any]]] | None = None
    _discovered_url: str
    _discovered_name: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose which server to add."""
        if user_input is not None:
            self._server_type = ServerType(user_input[CONF_SERVER_TYPE])
            if self._server_type is ServerType.SPLASH:
                return await self.async_step_splash_setup()
            return await self.async_step_server()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVER_TYPE, default=ServerType.SPLASH.value): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {"value": server_type.value, "label": backend.name}
                                    for server_type, backend in BACKENDS.items()
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        )
                    )
                }
            ),
        )

    async def async_step_splash_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Offer discovery or manual setup for SPLASH."""
        return self.async_show_menu(
            step_id="splash_setup", menu_options=["discover", "manual"]
        )

    async def async_step_server(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Set up a server of the selected type."""
        return await self._async_server_form("server", self._server_type, user_input)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add a server by its known address."""
        return await self.async_step_server(user_input)

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
            endpoint: f"Splash ({URL(endpoint).host})"
            for endpoint, status in self._scan.result().items()
            if not self._is_configured(ServerType.SPLASH, endpoint, status)
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

        if self._is_configured(ServerType.SPLASH, endpoint, status):
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
        return await self._async_server_form("confirm", ServerType.SPLASH, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update the settings of an existing server."""
        entry = self._get_reconfigure_entry()
        server_type = ServerType(entry.data.get(CONF_SERVER_TYPE, ServerType.SPLASH))
        return await self._async_server_form(
            "reconfigure", server_type, user_input, entry
        )

    def _is_configured(
        self,
        server_type: ServerType,
        endpoint: str,
        status: dict[str, Any],
        *,
        model: str = "",
        exclude: config_entries.ConfigEntry | None = None,
    ) -> bool:
        """Match an existing URL or an alternate address for the same process."""
        identity = instance_id(status)
        for existing in self._async_current_entries(include_ignore=False):
            if (
                existing is exclude
                or existing.data.get(CONF_SERVER_TYPE, ServerType.SPLASH) != server_type
                or existing.data.get(CONF_MODEL, "") != model
            ):
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
        self,
        step_id: str,
        server_type: ServerType,
        user_input: dict[str, Any] | None,
        entry: config_entries.ConfigEntry | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Validate settings and save them after a successful request."""
        backend = BACKENDS[server_type]
        confirming = step_id == "confirm"
        old_api_key = entry.data.get(CONF_API_KEY, "") if entry is not None else ""
        errors = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY, "").strip() or old_api_key
            if user_input.get(CONF_CLEAR_API_KEY):
                api_key = ""
            model = user_input.get(CONF_MODEL, "").strip()
            try:
                endpoint = (
                    self._discovered_url
                    if confirming
                    else monitoring_url(
                        user_input[CONF_URL],
                        path=backend.path,
                        default_port=backend.port,
                    )
                )
                status = await async_fetch_status(
                    async_get_clientsession(self.hass),
                    server_type,
                    endpoint,
                    api_key=api_key,
                    model=model,
                )
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            except AuthenticationError:
                errors[CONF_API_KEY] = "invalid_auth"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except MetricsUnavailableError:
                errors["base"] = "metrics_unavailable"
            except InvalidStatusError:
                errors["base"] = "invalid_status"
            else:
                if server_type is not ServerType.SPLASH and not status["ready"]:
                    errors["base"] = "not_ready"
                elif self._is_configured(
                    server_type, endpoint, status, model=model, exclude=entry
                ):
                    errors["base" if confirming else CONF_URL] = "already_configured"
                else:
                    title = user_input[CONF_NAME]
                    data = {
                        CONF_SERVER_TYPE: server_type.value,
                        CONF_URL: endpoint,
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    }
                    if api_key:
                        data[CONF_API_KEY] = api_key
                    if model:
                        data[CONF_MODEL] = model
                    if entry is not None:
                        return self.async_update_reload_and_abort(
                            entry, title=title, data=data
                        )
                    return self.async_create_entry(title=title, data=data)

        schema = CONFIRM_SCHEMA if confirming else FORM_SCHEMA
        if server_type is not ServerType.SPLASH:
            schema = schema.extend(
                {
                    vol.Optional(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            )
        if old_api_key:
            schema = schema.extend(
                {vol.Optional(CONF_CLEAR_API_KEY): selector.BooleanSelector()}
            )
        if server_type is ServerType.LLAMA_CPP:
            schema = schema.extend({vol.Optional(CONF_MODEL): str})

        suggestions = (
            {**entry.data, CONF_NAME: entry.title} if entry is not None else {}
        )
        if confirming:
            suggestions[CONF_NAME] = self._discovered_name
        if user_input:
            suggestions.update(user_input)
        suggestions.pop(CONF_API_KEY, None)
        placeholders = {"backend": backend.name, "port": str(backend.port)}
        if confirming:
            placeholders["url"] = self._discovered_url
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggestions),
            description_placeholders=placeholders,
            errors=errors,
        )
