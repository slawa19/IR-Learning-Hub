"""ZHA transport adapter for IR Learning Hub."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    ERROR_CLUSTER_NOT_FOUND,
    ERROR_LEARN_FAILED,
    ERROR_SEND_FAILED,
    ERROR_ZHA_DEVICE_NOT_FOUND,
    ERROR_ZHA_UNAVAILABLE,
)
from .device_profiles import get_profile
from .errors import IRLearningHubError
from .zha_compat import find_zha_cluster, get_zha_device_proxy

_LOGGER = logging.getLogger(__name__)


class ZHAAdapter:
    """Adapter for TS1201/Zosung commands through ZHA."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the adapter."""
        self.hass = hass

    def _resolve_device_id(self, ieee: str) -> str:
        """Resolve IEEE address to device registry ID."""
        normalized_ieee = ieee.lower()
        devreg = dr.async_get(self.hass)
        for device in devreg.devices.values():
            for domain, identifier in device.identifiers:
                if domain == "zha" and str(identifier).lower() == normalized_ieee:
                    return device.id
        raise IRLearningHubError(
            ERROR_ZHA_DEVICE_NOT_FOUND,
            f"ZHA device {ieee} not found in registry",
        )

    async def async_learn(self, transmitter: dict[str, Any]) -> None:
        """Start IR learning mode."""
        profile = get_profile(transmitter["profile"])
        await self._issue_cluster_command(
            transmitter,
            profile["learn_command"]["command"],
            profile["learn_command"]["params_true"],
            ERROR_LEARN_FAILED,
        )

    async def async_send(self, transmitter: dict[str, Any], code: str) -> None:
        """Send an IR code."""
        if not code:
            raise IRLearningHubError(ERROR_SEND_FAILED, "IR code must not be empty")

        profile = get_profile(transmitter["profile"])
        await self._issue_cluster_command(
            transmitter,
            profile["send_command"]["command"],
            {"code": code},
            ERROR_SEND_FAILED,
        )

    async def async_read_last_code(self, transmitter: dict[str, Any]) -> str:
        """Read last learned IR code from ZHA attribute 0."""
        profile = get_profile(transmitter["profile"])
        ieee = transmitter["ieee"]
        endpoint_id = transmitter["config"]["endpoint_id"]
        cluster_id = transmitter["config"]["ir_control_cluster"]
        attr_id = profile["last_learned_attribute_id"]
        attr_name = profile["last_learned_attribute"]

        try:
            device_id = self._resolve_device_id(ieee)
            zha_device_proxy = get_zha_device_proxy(self.hass, device_id)
        except IRLearningHubError:
            raise
        except Exception as err:
            raise IRLearningHubError(
                ERROR_ZHA_DEVICE_NOT_FOUND,
                f"ZHA device {ieee} was not found",
            ) from err

        cluster = find_zha_cluster(
            zha_device_proxy,
            endpoint_id,
            cluster_id,
            ieee,
        )

        attrs, failed = await cluster.read_attributes([attr_id])
        if failed:
            _LOGGER.debug("Reading attribute id %s failed: %s", attr_id, failed)
            attrs, failed = await cluster.read_attributes([attr_name])

        if failed:
            raise IRLearningHubError(
                ERROR_CLUSTER_NOT_FOUND,
                f"Could not read ZHA attribute 0x{attr_id:04X}: {failed}",
            )

        code = attrs.get(attr_id)
        if code is None:
            code = attrs.get(attr_name)
        if code is None:
            return ""
        return str(code)

    async def _issue_cluster_command(
        self,
        transmitter: dict[str, Any],
        command: int,
        params: dict[str, Any],
        error_code: str,
    ) -> None:
        """Call zha.issue_zigbee_cluster_command."""
        data = {
            "ieee": transmitter["ieee"],
            "endpoint_id": transmitter["config"]["endpoint_id"],
            "cluster_id": transmitter["config"]["ir_control_cluster"],
            "cluster_type": "in",
            "command": command,
            "command_type": "server",
            "params": params,
        }
        try:
            await self.hass.services.async_call(
                "zha",
                "issue_zigbee_cluster_command",
                data,
                blocking=True,
            )
        except Exception as err:
            raise IRLearningHubError(
                error_code,
                f"ZHA cluster command {command} failed: {err}",
            ) from err
