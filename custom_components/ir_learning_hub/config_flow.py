"""Config flow for IR Learning Hub."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import callback
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
    HUB_ENTRY_DATA,
    HUB_TITLE,
    TRANSMITTER_SUBENTRY_TYPE,
)
from .device_profiles import get_profile
from .storage import normalize_ieee

MANUAL_DEVICE = "__manual__"
MANUAL_SETUP_LABELS = {
    "en": "Manual setup",
    "ru": "Ручная настройка",
    "uk": "Ручне налаштування",
}
class _TransmitterFlowMixin:
    """Shared transmitter discovery/manual helpers."""

    _discovered: dict[str, dict[str, Any]]

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

    def _async_transmitter_choice_form(
        self,
        errors: dict[str, str],
    ) -> FlowResult:
        """Show the discovery/manual transmitter selection form."""
        choices = {
            device_id: item["label"]
            for device_id, item in sorted(
                self._discovered.items(),
                key=lambda entry: entry[1]["label"].casefold(),
            )
        }
        choices[MANUAL_DEVICE] = _manual_setup_label(self.hass.config.language)

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

    def _async_manual_form(
        self,
        errors: dict[str, str],
    ) -> FlowResult:
        """Show the manual transmitter form."""
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

    @staticmethod
    def _normalize_transmitter_input(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize one transmitter payload for entry/subentry storage."""
        normalized = dict(data)
        normalized[CONF_IEEE] = str(data[CONF_IEEE]).strip().lower()
        return {
            CONF_IEEE: normalized[CONF_IEEE],
            CONF_PROFILE: normalized[CONF_PROFILE],
            CONF_ENDPOINT_ID: normalized[CONF_ENDPOINT_ID],
            CONF_CLUSTER_ID: normalized[CONF_CLUSTER_ID],
            CONF_LEARN_TIMEOUT: normalized[CONF_LEARN_TIMEOUT],
            CONF_LEARN_REASSERT_INTERVAL: normalized[CONF_LEARN_REASSERT_INTERVAL],
        }

    @staticmethod
    def _transmitter_title(data: dict[str, Any]) -> str:
        """Return a human-friendly transmitter title."""
        return data.get("label") or f"IR transmitter {data[CONF_IEEE]}"


class IRLearningHubConfigFlow(
    _TransmitterFlowMixin,
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle an IR Learning Hub config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered: dict[str, dict[str, Any]] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return supported config subentry types."""
        return {TRANSMITTER_SUBENTRY_TYPE: IRLearningHubTransmitterSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the hub and seed its first transmitter subentry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        self._discovered = await self._async_discover_zha_transmitters()

        if user_input is not None:
            selected = user_input[CONF_ZHA_DEVICE]
            if selected == MANUAL_DEVICE:
                return await self.async_step_manual()

            if selected in self._discovered:
                data = dict(self._discovered[selected])
                data[CONF_LEARN_TIMEOUT] = user_input[CONF_LEARN_TIMEOUT]
                data[CONF_LEARN_REASSERT_INTERVAL] = user_input[
                    CONF_LEARN_REASSERT_INTERVAL
                ]
                return self._async_create_hub_entry(data)

            errors[CONF_ZHA_DEVICE] = "device_not_found"

        return self._async_transmitter_choice_form(errors)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the first transmitter manually."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return self._async_create_hub_entry(user_input)

        return self._async_manual_form(errors)

    def _async_create_hub_entry(self, data: dict[str, Any]) -> FlowResult:
        """Create the hub entry with its initial transmitter subentry."""
        transmitter_data = self._normalize_transmitter_input(data)
        return self.async_create_entry(
            title=HUB_TITLE,
            data=HUB_ENTRY_DATA,
            subentries=[
                {
                    "data": transmitter_data,
                    "subentry_type": TRANSMITTER_SUBENTRY_TYPE,
                    "title": self._transmitter_title(data),
                    "unique_id": normalize_ieee(transmitter_data[CONF_IEEE]),
                }
            ],
        )


class IRLearningHubTransmitterSubentryFlow(
    _TransmitterFlowMixin,
    config_entries.ConfigSubentryFlow,
):
    """Handle transmitter config subentries."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        self._discovered: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a transmitter subentry to the hub."""
        errors: dict[str, str] = {}
        self._discovered = await self._async_discover_zha_transmitters()

        if user_input is not None:
            selected = user_input[CONF_ZHA_DEVICE]
            if selected == MANUAL_DEVICE:
                return await self.async_step_manual()

            if selected in self._discovered:
                data = dict(self._discovered[selected])
                data[CONF_LEARN_TIMEOUT] = user_input[CONF_LEARN_TIMEOUT]
                data[CONF_LEARN_REASSERT_INTERVAL] = user_input[
                    CONF_LEARN_REASSERT_INTERVAL
                ]
                return self._async_create_subentry(data)

            errors[CONF_ZHA_DEVICE] = "device_not_found"

        return self._async_transmitter_choice_form(errors)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a transmitter subentry manually."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return self._async_create_subentry(user_input)

        return self._async_manual_form(errors)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Reconfigure transmitter timing values."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self.hass.config_entries.async_get_known_entry(self._entry_id),
                subentry,
                data_updates={
                    CONF_LEARN_TIMEOUT: user_input[CONF_LEARN_TIMEOUT],
                    CONF_LEARN_REASSERT_INTERVAL: user_input[
                        CONF_LEARN_REASSERT_INTERVAL
                    ],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LEARN_TIMEOUT,
                    default=subentry.data[CONF_LEARN_TIMEOUT],
                ): int,
                vol.Required(
                    CONF_LEARN_REASSERT_INTERVAL,
                    default=subentry.data[CONF_LEARN_REASSERT_INTERVAL],
                ): int,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    def _async_create_subentry(self, data: dict[str, Any]) -> FlowResult:
        """Create a transmitter subentry after duplicate validation."""
        transmitter_data = self._normalize_transmitter_input(data)
        unique_id = normalize_ieee(transmitter_data[CONF_IEEE])
        entry = self.hass.config_entries.async_get_known_entry(self._entry_id)
        if any(
            subentry.unique_id == unique_id
            for subentry in entry.get_subentries_of_type(TRANSMITTER_SUBENTRY_TYPE)
        ):
            return self.async_abort(reason="already_configured")

        return self.async_create_entry(
            title=self._transmitter_title(data),
            data=transmitter_data,
            unique_id=unique_id,
        )


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


def _manual_setup_label(language: str | None) -> str:
    """Return a localized label for the manual dynamic option."""
    lang = (language or "en").split("-")[0]
    return MANUAL_SETUP_LABELS.get(lang, MANUAL_SETUP_LABELS["en"])


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
