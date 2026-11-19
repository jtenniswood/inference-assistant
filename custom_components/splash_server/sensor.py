"""Numeric and text statistics from a SPLASH server."""

from dataclasses import dataclass
from math import isfinite

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import status_value
from .coordinator import SplashConfigEntry, SplashCoordinator


@dataclass(frozen=True, kw_only=True)
class SplashSensorDescription(SensorEntityDescription):
    """Map a sensor to a value in the status document."""

    path: tuple[str, ...]
    count_items: bool = False
    check_batch: bool = False


def metric(key: str, path: str, **kwargs) -> SplashSensorDescription:
    """Describe a translated sensor and its status field."""
    return SplashSensorDescription(
        key=key,
        translation_key=key,
        path=tuple(path.split(".")),
        **kwargs,
    )


DATA_SIZE = {
    "device_class": SensorDeviceClass.DATA_SIZE,
    "native_unit_of_measurement": UnitOfInformation.BYTES,
    "suggested_unit_of_measurement": UnitOfInformation.GIBIBYTES,
    "state_class": SensorStateClass.MEASUREMENT,
}
RATE = {
    "native_unit_of_measurement": PERCENTAGE,
    "suggested_display_precision": 1,
    "state_class": SensorStateClass.MEASUREMENT,
}
SPEED = {
    "native_unit_of_measurement": "tokens/s",
    "suggested_display_precision": 1,
    "state_class": SensorStateClass.MEASUREMENT,
}
DURATION = {
    "device_class": SensorDeviceClass.DURATION,
    "native_unit_of_measurement": UnitOfTime.MILLISECONDS,
    "suggested_display_precision": 1,
    "state_class": SensorStateClass.MEASUREMENT,
}

SENSORS = (
    metric(
        "active_requests",
        "active_requests",
        count_items=True,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric(
        "queued_requests", "scheduler.queued", state_class=SensorStateClass.MEASUREMENT
    ),
    metric(
        "waiting_requests",
        "admission.waiting",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric(
        "prefilling_requests",
        "scheduler.prefilling",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric(
        "decoding_requests",
        "scheduler.decoding",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric(
        "submitted_requests",
        "requests.submitted",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "completed_requests",
        "requests.completed",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "cancelled_requests",
        "requests.cancelled",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "failed_requests",
        "requests.failed",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric("model", "instance.model"),
    metric(
        "maximum_context_tokens",
        "maximum_context_tokens",
        native_unit_of_measurement="tokens",
    ),
    metric("memory_pressure", "memory_pressure"),
    metric("thermal_state", "thermal_state"),
    metric("memory_current", "memory_actual.current_bytes", **DATA_SIZE),
    metric("memory_allocated", "memory_actual.allocated_bytes", **DATA_SIZE),
    metric("memory_peak", "memory_actual.peak_bytes", **DATA_SIZE),
    metric("memory_limit", "memory_governor.limit_bytes", **DATA_SIZE),
    metric("memory_headroom", "memory_governor.headroom_bytes", **DATA_SIZE),
    metric(
        "host_available_memory", "memory_governor.host_available_bytes", **DATA_SIZE
    ),
    metric("kv_cache_memory", "kv.allocated_bytes", **DATA_SIZE),
    metric("kv_cache_active_memory", "kv.active_bytes", **DATA_SIZE),
    metric(
        "kv_cache_active_pages",
        "kv.pages_active",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric("disk_cache_used", "disk.used_bytes", **DATA_SIZE),
    metric("disk_cache_limit", "disk.limit_bytes", **DATA_SIZE),
    metric("disk_volume_available", "disk.volume_available_bytes", **DATA_SIZE),
    metric("cache_hits", "cache.hits", state_class=SensorStateClass.TOTAL_INCREASING),
    metric(
        "cache_cold_misses",
        "cache.cold_misses",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric("cache_hit_rate", "cache.hit_rate", **RATE),
    metric(
        "cache_reused_tokens",
        "cache.reused_tokens",
        native_unit_of_measurement="tokens",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "prefill_tokens",
        "metrics.prefill_input_tokens",
        native_unit_of_measurement="tokens",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "decode_tokens",
        "metrics.decode_output_tokens",
        native_unit_of_measurement="tokens",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric("prefill_speed", "metrics.prefill_tokens_per_second", **SPEED),
    metric("decode_speed", "metrics.decode_tokens_per_second", **SPEED),
    metric(
        "last_prefill_speed",
        "metrics.current_prefill_batch.tokens_per_second",
        **SPEED,
        check_batch=True,
    ),
    metric(
        "last_decode_speed",
        "metrics.current_decode_batch.tokens_per_second",
        **SPEED,
        check_batch=True,
    ),
    metric("draft_acceptance_rate", "metrics.draft_acceptance_rate", **RATE),
    metric("ttft_p50", "metrics.ttft_ms.p50", **DURATION),
    metric("ttft_p95", "metrics.ttft_ms.p95", **DURATION),
    metric("itl_p50", "metrics.itl_ms.p50", **DURATION),
    metric("itl_p95", "metrics.itl_ms.p95", **DURATION),
    metric(
        "active_http_connections",
        "http.connections.active",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    metric(
        "transport_restarts",
        "transport.restarts",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    metric(
        "schema_version", "schema_version", entity_category=EntityCategory.DIAGNOSTIC
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SplashConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the sensors for one server."""
    async_add_entities(SplashSensor(entry, description) for description in SENSORS)


class SplashSensor(CoordinatorEntity[SplashCoordinator], SensorEntity):
    """A statistic updated by the shared status poll."""

    _attr_has_entity_name = True
    entity_description: SplashSensorDescription

    def __init__(
        self, entry: SplashConfigEntry, description: SplashSensorDescription
    ) -> None:
        """Assign an identity that survives address or name changes."""
        super().__init__(entry.runtime_data)
        self.entity_description = description
        self._attr_device_info = self.coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> str | int | float | None:
        """Return the current statistic with its Home Assistant unit."""
        description = self.entity_description
        data = self.coordinator.data
        if description.check_batch:
            valid_path = (*description.path[:-1], "valid")
            if status_value(data, valid_path) is not True:
                return None

        value = status_value(data, description.path)
        if description.count_items:
            return len(value) if isinstance(value, list) else None
        if type(value) in (int, float) and isfinite(value):
            return (
                value * 100
                if description.native_unit_of_measurement == PERCENTAGE
                else value
            )
        if isinstance(value, str) and description.state_class is None:
            return value if len(value) <= 255 else value[:255]
        return None
