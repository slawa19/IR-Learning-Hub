"""Compatibility helpers for private ZHA proxy access."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import ERROR_CLUSTER_NOT_FOUND, ERROR_ZHA_UNAVAILABLE
from .device_profiles import get_profile
from .errors import IRLearningHubError

_LOGGER = logging.getLogger(__name__)


def get_zha_device_proxy(hass: HomeAssistant, device_id: str) -> Any:
    """Return the ZHA device proxy for a Home Assistant device registry id."""
    try:
        from homeassistant.components.zha.helpers import async_get_zha_device_proxy
    except ImportError as err:
        raise IRLearningHubError(
            ERROR_ZHA_UNAVAILABLE,
            "ZHA helper async_get_zha_device_proxy is not available",
        ) from err

    try:
        # Despite the name, this helper is synchronous in supported HA versions.
        return async_get_zha_device_proxy(hass, device_id)
    except IRLearningHubError:
        raise
    except Exception as err:
        raise IRLearningHubError(
            ERROR_ZHA_UNAVAILABLE,
            f"ZHA device proxy is not available: {err}",
        ) from err


def iter_zha_nested_devices(zha_device_proxy: Any) -> list[Any]:
    """Return ZHA proxy and nested zigpy device objects without duplicates."""
    devices = []
    seen_ids = set()
    device = zha_device_proxy
    while device is not None and id(device) not in seen_ids:
        seen_ids.add(id(device))
        devices.append(device)
        device = getattr(device, "device", None)
    return devices


def find_zha_cluster(
    zha_device_proxy: Any,
    endpoint_id: int,
    cluster_id: int,
    ieee: str | None = None,
) -> Any:
    """Find a ZHA/zigpy cluster through wrapper and nested device objects."""
    saw_endpoint_container = False
    for candidate in iter_zha_nested_devices(zha_device_proxy):
        endpoints = getattr(candidate, "endpoints", None)
        if endpoints is None:
            continue
        saw_endpoint_container = True
        endpoint = endpoints.get(endpoint_id)
        if endpoint is None:
            continue

        cluster = getattr(endpoint, "in_clusters", {}).get(cluster_id)
        if cluster is None:
            named_cluster = getattr(endpoint, "zosung_ircontrol", None)
            candidate_cluster_id = getattr(named_cluster, "cluster_id", None)
            if candidate_cluster_id == cluster_id:
                cluster = named_cluster
        if cluster is not None:
            _LOGGER.debug("Using ZHA cluster from %s", type(candidate))
            return cluster

    if not saw_endpoint_container:
        raise IRLearningHubError(
            ERROR_ZHA_UNAVAILABLE,
            "ZHA device proxy shape is not supported by IR Learning Hub",
        )

    suffix = f" for {ieee}" if ieee else ""
    raise IRLearningHubError(
        ERROR_CLUSTER_NOT_FOUND,
        f"Cluster {cluster_id} (0x{cluster_id:04X}) was not found on endpoint {endpoint_id}{suffix}",
    )


def detect_ir_control_cluster(
    zha_device_proxy: Any,
    profile_id: str,
) -> tuple[int, int] | None:
    """Detect endpoint and IR control cluster values for a device profile."""
    profile = get_profile(profile_id)
    control_cluster = profile["ir_control_cluster"]
    saw_endpoint_container = False

    for device in iter_zha_nested_devices(zha_device_proxy):
        endpoints = getattr(device, "endpoints", None)
        if endpoints is None:
            continue
        saw_endpoint_container = True
        endpoints = endpoints or {}
        for endpoint_id, endpoint in endpoints.items():
            in_clusters = getattr(endpoint, "in_clusters", {}) or {}
            if control_cluster in in_clusters:
                return int(endpoint_id), int(control_cluster)

            cluster = getattr(endpoint, "zosung_ircontrol", None)
            if cluster is not None:
                cluster_id = getattr(cluster, "cluster_id", control_cluster)
                return int(endpoint_id), int(cluster_id)
    if not saw_endpoint_container:
        raise IRLearningHubError(
            ERROR_ZHA_UNAVAILABLE,
            "ZHA device proxy shape is not supported by IR Learning Hub",
        )
    return None
