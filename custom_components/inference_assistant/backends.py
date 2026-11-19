"""Read status from the supported LLM server APIs."""

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from prometheus_client.parser import text_string_to_metric_families
from prometheus_client.samples import Sample
from yarl import URL

from .api import CannotConnectError, InvalidStatusError, async_get_status, status_value
from .const import DEFAULT_PORT, REQUEST_TIMEOUT

CONF_SERVER_TYPE = "server_type"
CONF_CLEAR_API_KEY = "clear_api_key"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ServerType(StrEnum):
    """Supported server families."""

    SPLASH = "splash"
    OLLAMA = "ollama"
    LM_STUDIO = "lm_studio"
    LLAMA_CPP = "llama_cpp"
    VLLM = "vllm"


@dataclass(frozen=True)
class Backend:
    """The product name and default monitoring endpoint."""

    name: str
    port: int
    path: str


BACKENDS = {
    ServerType.SPLASH: Backend("Splash", DEFAULT_PORT, "/status"),
    ServerType.OLLAMA: Backend("Ollama", 11434, "/api/ps"),
    ServerType.LM_STUDIO: Backend("LM Studio", 1234, "/api/v1/models"),
    ServerType.LLAMA_CPP: Backend("llama.cpp", 8080, "/metrics"),
    ServerType.VLLM: Backend("vLLM", 8000, "/metrics"),
}

type Status = dict[str, Any]
type MetricSamples = dict[str, list[Sample]]


class AuthenticationError(CannotConnectError):
    """The server rejected the monitoring credentials."""


class MetricsUnavailableError(InvalidStatusError):
    """The server's metrics endpoint is missing or disabled."""


async def _async_read(
    session: ClientSession,
    url: URL,
    api_key: str,
    *,
    health_check: bool = False,
) -> bytes | bool:
    """Read a bounded response or return the result of a health check."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if url.path == "/metrics":
        headers["Accept"] = "text/plain; version=0.0.4"
    try:
        async with session.get(
            url,
            headers=headers,
            timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            allow_redirects=False,
        ) as response:
            if response.status in (401, 403):
                raise AuthenticationError(
                    f"Monitoring endpoint returned HTTP {response.status}"
                )
            if health_check and response.status in (200, 503):
                return response.status == 200
            if url.path == "/metrics" and response.status in (404, 501):
                raise MetricsUnavailableError(
                    "The metrics endpoint is disabled or missing"
                )
            if response.status != 200:
                raise CannotConnectError(
                    f"Monitoring endpoint returned HTTP {response.status}"
                )
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise InvalidStatusError("Monitoring response is too large")
            return bytes(body)
    except (ClientError, TimeoutError) as err:
        raise CannotConnectError("Could not reach the monitoring endpoint") from err


def _records(value: Any, *, name: str) -> list[Status]:
    """Validate a list of objects before reading its fields."""
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise InvalidStatusError(f"Missing or invalid {name} list")
    return value


def _number(value: Any) -> int | float | None:
    """Read a finite, non-negative count or measurement."""
    if type(value) is int and value >= 0:
        return value
    if type(value) is float and isfinite(value) and value >= 0:
        return value
    return None


def _sum_field(records: list[Status], key: str) -> int | float | None:
    """Sum a reported field when every record supplies it."""
    total = 0
    for record in records:
        if (value := _number(record.get(key))) is None:
            return None
        total += value
    return total


def _model_names(values: list[Any]) -> str | None:
    """Return a stable display name for the loaded or served models."""
    return (
        ", ".join(
            sorted({value for value in values if isinstance(value, str) and value})
        )
        or None
    )


def _max_context(values: list[Any]) -> int | float | None:
    """Return the largest reported configured context."""
    return max(
        (value for raw in values if (value := _number(raw)) is not None), default=None
    )


def _json_status(server_type: ServerType, body: bytes) -> Status:
    """Adapt the Ollama or LM Studio model inventory for sensors."""
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError) as err:
        raise InvalidStatusError("Monitoring response is not valid JSON") from err
    models = _records(status_value(payload, ("models",)), name="models")

    if server_type is ServerType.OLLAMA:
        if any(
            not isinstance(model.get("name") or model.get("model"), str)
            for model in models
        ):
            raise InvalidStatusError("Missing Ollama model names")
        return {
            "ready": True,
            "loaded_models": len(models),
            "loaded_model_names": _model_names(
                [model.get("name") or model.get("model") for model in models]
            ),
            "loaded_context": _max_context(
                [model.get("context_length") for model in models]
            ),
            "loaded_model_memory": _sum_field(models, "size"),
            "loaded_model_vram": _sum_field(models, "size_vram"),
        }

    loaded = [
        (model, _records(model.get("loaded_instances"), name="loaded instances"))
        for model in models
    ]
    instances = [instance for _, group in loaded for instance in group]
    parallel_slots = [
        parallel
        for instance in instances
        if (parallel := _number(status_value(instance, ("config", "parallel"))))
        is not None
    ]
    return {
        "ready": True,
        "loaded_models": sum(bool(group) for _, group in loaded),
        "loaded_model_names": _model_names(
            [
                model.get("display_name") or model.get("key")
                for model, group in loaded
                if group
            ]
        ),
        "loaded_instances": len(instances),
        "loaded_context": _max_context(
            [
                status_value(instance, ("config", "context_length"))
                for instance in instances
            ]
        ),
        "parallel_capacity": sum(parallel_slots) if parallel_slots else None,
    }


def _metrics(body: bytes, prefix: str) -> MetricSamples:
    """Parse and retain finite samples for the selected server family."""
    metrics: MetricSamples = defaultdict(list)
    try:
        for family in text_string_to_metric_families(body.decode()):
            for sample in family.samples:
                if sample.name.startswith(prefix) and _number(sample.value) is not None:
                    metrics[sample.name.removeprefix(prefix)].append(sample)
    except (ValueError, OverflowError) as err:
        raise InvalidStatusError("Invalid Prometheus metrics response") from err
    if not metrics:
        raise InvalidStatusError("No metrics for the selected server type")
    return metrics


def _total(metrics: MetricSamples, name: str) -> float | None:
    """Sum samples across engines and accept canonical counter names."""
    samples = metrics.get(name) or metrics.get(f"{name}_total")
    return sum(sample.value for sample in samples) if samples else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Compute a ratio when both inputs are available."""
    return numerator / denominator if numerator is not None and denominator else None


def _metrics_status(server_type: ServerType, body: bytes, model: str) -> Status:
    """Adapt the metrics exposed by llama.cpp or vLLM."""
    if server_type is ServerType.LLAMA_CPP:
        metrics = _metrics(body, "llamacpp:")
        return {
            "ready": True,
            "served_models": model or None,
            "active_requests": _total(metrics, "requests_processing"),
            "queued_requests": _total(metrics, "requests_deferred"),
            "prefill_speed": _total(metrics, "prompt_tokens_seconds"),
            "decode_speed": _total(metrics, "predicted_tokens_seconds"),
            "prefill_tokens": _total(metrics, "prompt_tokens"),
            "decode_tokens": _total(metrics, "tokens_predicted"),
        }

    metrics = _metrics(body, "vllm:")
    cache_usage = metrics.get("kv_cache_usage_perc") or metrics.get(
        "gpu_cache_usage_perc", []
    )
    return {
        "ready": True,
        "served_models": _model_names(
            [
                sample.labels.get("model_name")
                for samples in metrics.values()
                for sample in samples
            ]
        ),
        "active_requests": _total(metrics, "num_requests_running"),
        "queued_requests": _total(metrics, "num_requests_waiting"),
        "kv_cache_usage": max((sample.value for sample in cache_usage), default=None),
        "prefix_cache_hit_rate": _ratio(
            _total(metrics, "prefix_cache_hits"),
            _total(metrics, "prefix_cache_queries"),
        ),
        "ttft_average": _ratio(
            _total(metrics, "time_to_first_token_seconds_sum"),
            _total(metrics, "time_to_first_token_seconds_count"),
        ),
        "prefill_tokens": _total(metrics, "prompt_tokens"),
        "decode_tokens": _total(metrics, "generation_tokens"),
        "preemptions": _total(metrics, "num_preemptions"),
    }


async def async_fetch_status(
    session: ClientSession,
    server_type: ServerType,
    endpoint: str,
    *,
    api_key: str = "",
    model: str = "",
) -> Status:
    """Poll the backend without invoking inference or loading a model."""
    if server_type is ServerType.SPLASH:
        return await async_get_status(session, endpoint)

    url = URL(endpoint)
    if server_type in (ServerType.OLLAMA, ServerType.LM_STUDIO):
        body = await _async_read(session, url, api_key)
        assert isinstance(body, bytes)
        return _json_status(server_type, body)

    if not await _async_read(
        session, url.with_path("/health"), api_key, health_check=True
    ):
        return {"ready": False}
    if server_type is ServerType.LLAMA_CPP and model:
        url = url.with_query(model=model, autoload="false")

    body = await _async_read(session, url, api_key)
    assert isinstance(body, bytes)
    return await asyncio.to_thread(_metrics_status, server_type, body, model)
