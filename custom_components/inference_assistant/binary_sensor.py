"""Readiness and health indicators for an inference server."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import status_value
from .backends import ServerType
from .coordinator import InferenceConfigEntry, InferenceCoordinator

BINARY_SENSORS = {
    "ready": ("ready",),
    "metal_healthy": (
        "metal",
        "healthy",
    ),
    "status_stale": (
        "transport",
        "status_stale",
    ),
    "draining": (
        "admission",
        "draining",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InferenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the binary sensors for one server."""
    if entry.runtime_data.server_type is ServerType.SPLASH:
        async_add_entities(
            InferenceBinarySensor(entry, key, path)
            for key, path in BINARY_SENSORS.items()
        )
    else:
        async_add_entities(
            [InferenceBinarySensor(entry, "ready", BINARY_SENSORS["ready"])]
        )


class InferenceBinarySensor(
    CoordinatorEntity[InferenceCoordinator], BinarySensorEntity
):
    """A True/False statistic updated by the shared status poll."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: InferenceConfigEntry, key: str, path: tuple[str, ...]
    ) -> None:
        """Assign an identity that survives address or name changes."""
        super().__init__(entry.runtime_data)
        self._path = path
        self._attr_translation_key = key
        self._attr_entity_category = (
            None if key == "ready" else EntityCategory.DIAGNOSTIC
        )
        self._attr_device_info = self.coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def is_on(self) -> bool | None:
        """Return the server's reported flag."""
        value = status_value(self.coordinator.data, self._path)
        return value if isinstance(value, bool) else None
