"""Client for the SPLASH server status endpoint."""

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from yarl import URL

from .const import DEFAULT_PORT, REQUEST_TIMEOUT


class InvalidStatusError(Exception):
    """The server did not return SPLASH status data."""


class CannotConnectError(Exception):
    """The status request failed."""


def status_url(address: str) -> str:
    """Normalize a server address to its status endpoint."""
    address = address.strip()
    if not address or any(char.isspace() for char in address):
        raise ValueError("Enter an IP address, hostname, or HTTP(S) URL")
    has_scheme = "://" in address
    url = URL(address if has_scheme else f"http://{address}")
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.user is not None
        or url.path not in {"", "/", "/status", "/status/"}
        or url.query_string
        or url.fragment
    ):
        raise ValueError("Enter an IP address, hostname, or HTTP(S) status URL")

    # With an explicit scheme, honor HTTP/HTTPS defaults if no port was given.
    port = DEFAULT_PORT if not has_scheme and url.explicit_port is None else url.port
    if not port:
        raise ValueError("Port must be between 1 and 65535")
    return str(url.with_port(port).with_path("/status"))


async def async_get_status(session: ClientSession, endpoint: str) -> dict[str, Any]:
    """Fetch and validate the status document."""
    try:
        async with session.get(
            endpoint,
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise CannotConnectError(
                    f"Status endpoint returned HTTP {response.status}"
                )
            try:
                data = await response.json(content_type=None)
            except ValueError as err:
                raise InvalidStatusError("Status response is not valid JSON") from err
    except (ClientError, TimeoutError) as err:
        raise CannotConnectError("Could not reach the status endpoint") from err

    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or type(data.get("ready")) is not bool
    ):
        raise InvalidStatusError("Missing SPLASH schema version or readiness")
    return data


def status_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Return a nested status value, tolerating optional sections."""
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
