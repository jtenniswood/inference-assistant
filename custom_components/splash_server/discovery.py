"""Find Splash status endpoints on the local network."""

import asyncio
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from itertools import batched
from typing import Any

from homeassistant.components import network
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from .api import CannotConnectError, InvalidStatusError, async_get_status, status_value
from .const import DEFAULT_PORT

_PRIVATE_NETWORKS = tuple(
    IPv4Network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_MAX_HOSTS = 1024
_CONCURRENCY = 32
_PROBE_TIMEOUT = 1


def instance_id(status: dict[str, Any]) -> str | None:
    """Return the ID of this running server process."""
    value = status_value(status, ("instance", "id"))
    return value if isinstance(value, str) and value else None


async def async_probe(hass: HomeAssistant, endpoint: str) -> dict[str, Any] | None:
    """Verify that a discovery candidate actually serves Splash status."""
    try:
        status = await async_get_status(
            async_get_clientsession(hass), endpoint, timeout=_PROBE_TIMEOUT
        )
    except (CannotConnectError, InvalidStatusError):
        return None

    # Splash's HTTP layer adds these fields to the engine's status response.
    if (
        instance_id(status)
        and isinstance(status_value(status, ("instance", "model")), str)
        and type(status_value(status, ("instance", "port"))) is int
        and isinstance(status.get("http"), dict)
    ):
        return status
    return None


async def async_candidate_hosts(hass: HomeAssistant) -> list[IPv4Address]:
    """Get IPv4 hosts on enabled private adapters, starting with the default."""
    adapters = await network.async_get_adapters(hass)
    hosts: dict[IPv4Address, None] = {}
    for adapter in sorted(adapters, key=lambda adapter: not adapter["default"]):
        if not adapter["enabled"]:
            continue
        for address in adapter["ipv4"]:
            local = IPv4Address(address["address"])
            if not any(local in subnet for subnet in _PRIVATE_NETWORKS):
                continue
            # Limit larger networks to the adapter's own /24.
            prefix = max(24, address["network_prefix"])
            for host in IPv4Interface((local, prefix)).network.hosts():
                hosts[host] = None
                if len(hosts) == _MAX_HOSTS:
                    return list(hosts)
    return list(hosts)


async def async_discover(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Check the default Splash port on local candidates once."""
    endpoints = (
        str(URL.build(scheme="http", host=str(host), port=DEFAULT_PORT, path="/status"))
        for host in await async_candidate_hosts(hass)
    )
    found = {}
    seen = set()
    for batch in batched(endpoints, _CONCURRENCY):
        statuses = await asyncio.gather(
            *(async_probe(hass, endpoint) for endpoint in batch)
        )
        for endpoint, status in zip(batch, statuses, strict=True):
            if status is not None and (identity := instance_id(status)) not in seen:
                found[endpoint] = status
                seen.add(identity)
    return found
