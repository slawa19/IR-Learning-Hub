"""Config flow for IR Learning Hub."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CLUSTER_ID,
    CONF_ENDPOINT_ID,
    CONF_IEEE,
    CONF_LEARN_REASSERT_INTERVAL,
    CONF_LEARN_TIMEOUT,
    CONF_PROFILE,
    CONF_ZHA_DEVICE,
    DEFAULT_CLUSTER_ID,
    DEFAULT_ENDPOINT_ID,
    DEFAULT_LEARN_REASSERT_INTERVAL,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_PROFILE,
    DOMAIN,
)
from .device_profiles import get_profile
from .storage import normalize_ieee

MANUAL_DEVICE = "__manual__"


class IRLearningHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an IR Learning Hub config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure one ZHA IR transmitter."""
        errors: dict[str, str] = {}
        self._discovered = await self._async_discover_zha_transmitters()

        if user_input is not None:
            selected = user_input[CONF_ZHA_DEVICE]
            if selected == MANUAL_DEVICE:
                return await self.async_step_manual()

            data = dict(self._discovered[selected])
            data[CONF_LEARN_TIMEOUT] = user_input[CONF_LEARN_TIMEOUT]
            data[CONF_LEARN_REASSERT_INTERVAL] = user_input[
                CONF_LEARN_REASSERT_INTERVAL
            ]
            return await self._async_create_transmitter_entry(data)

        choices = {
            device_id: item["label"]
            for device_id, item in sorted(
                self._discovered.items(),
                key=lambda entry: entry[1]["label"].casefold(),
            )
        }
        choices[MANUAL_DEVICE] = "Enter device details manually"

        schema = vol.Schema(
            {
                vol.Required(CONF_ZHA_DEVICE): vol.In(choices),
                vol.Required(
                    CONF_LEARN_TIMEOUT,
                    default=DEFAULT_LEARN_TIMEOUT,
                ): int,
                vol.Required(
                    CONF_LEARN_REASSERT_INTERVAL,
                    default=DEFAULT_LEARN_REASSERT_INTERVAL,
                ): int,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure an IR transmitter manually."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = dict(user_input)
            data[CONF_IEEE] = user_input[CONF_IEEE].strip().lower()
            return await self._async_create_transmitter_entry(data)

        schema = vol.Schema(
            {
                vol.Required(CONF_IEEE): str,
                vol.Required(CONF_PROFILE, default=DEFAULT_PROFILE): vol.In(
                    [DEFAULT_PROFILE]
                ),
                vol.Required(CONF_ENDPOINT_ID, default=DEFAULT_ENDPOINT_ID): int,
                vol.Required(CONF_CLUSTER_ID, default=DEFAULT_CLUSTER_ID): int,
                vol.Required(
                    CONF_LEARN_TIMEOUT,
                    default=DEFAULT_LEARN_TIMEOUT,
                ): int,
                vol.Required(
                    CONF_LEARN_REASSERT_INTERVAL,
                    default=DEFAULT_LEARN_REASSERT_INTERVAL,
                ): int,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors=errors,
        )

    async def _async_create_transmitter_entry(
        self,
        data: dict[str, Any],
    ) -> FlowResult:
        """Create a config entry for one transmitter."""
        ieee = data[CONF_IEEE].strip().lower()
        await self.async_set_unique_id(normalize_ieee(ieee))
        self._abort_if_unique_id_configured()

        data[CONF_IEEE] = ieee
        title = data.pop("label", None) or f"IR Learning Hub {ieee}"
        return self.async_create_entry(title=title, data=data)

    async def _async_discover_zha_transmitters(self) -> dict[str, dict[str, Any]]:
        """Find ZHA devices exposing the known IR control cluster."""
        try:
            from homeassistant.components.zha.helpers import async_get_zha_device_proxy
        except ImportError:
            return {}

        devreg = dr.async_get(self.hass)
        discovered: dict[str, dict[str, Any]] = {}
        for device in devreg.devices.values():
            ieee = _zha_ieee(device)
            if ieee is None:
                continue

            try:
                zha_device_proxy = async_get_zha_device_proxy(self.hass, device.id)
            except Exception:
                continue

            detected = _detect_profile_config(zha_device_proxy)
            if detected is None:
                continue

            endpoint_id, cluster_id = detected
            discovered[device.id] = {
                CONF_IEEE: ieee,
                CONF_PROFILE: DEFAULT_PROFILE,
                CONF_ENDPOINT_ID: endpoint_id,
                CONF_CLUSTER_ID: cluster_id,
                "label": _device_label(device, ieee),
            }
        return discovered


def _zha_ieee(device: dr.DeviceEntry) -> str | None:
    """Return the ZHA IEEE identifier for a device registry entry."""
    for domain, identifier in device.identifiers:
        if domain == "zha":
            return str(identifier).lower()
    return None


def _device_label(device: dr.DeviceEntry, ieee: str) -> str:
    """Build a readable config-flow label for a ZHA device."""
    name = device.name_by_user or device.name or ieee
    parts = [name]
    if device.manufacturer:
        parts.append(str(device.manufacturer))
    if device.model:
        parts.append(str(device.model))
    parts.append(ieee)
    return " · ".join(parts)


def _detect_profile_config(zha_device_proxy: Any) -> tuple[int, int] | None:
    """Detect endpoint and cluster values for the known transmitter profile."""
    profile = get_profile(DEFAULT_PROFILE)
    control_cluster = profile["ir_control_cluster"]

    for device in _iter_nested_devices(zha_device_proxy):
        endpoints = getattr(device, "endpoints", {}) or {}
        for endpoint_id, endpoint in endpoints.items():
            in_clusters = getattr(endpoint, "in_clusters", {}) or {}
            if control_cluster in in_clusters:
                return int(endpoint_id), int(control_cluster)

            cluster = getattr(endpoint, "zosung_ircontrol", None)
            if cluster is not None:
                cluster_id = getattr(cluster, "cluster_id", control_cluster)
                return int(endpoint_id), int(cluster_id)
    return None


def _iter_nested_devices(zha_device_proxy: Any) -> list[Any]:
    """Return ZHA proxy and nested zigpy device objects without duplicates."""
    devices = []
    seen_ids = set()
    device = getattr(zha_device_proxy, "device", None)
    while device is not None and id(device) not in seen_ids:
        seen_ids.add(id(device))
        devices.append(device)
        device = getattr(device, "device", None)
    return devices
