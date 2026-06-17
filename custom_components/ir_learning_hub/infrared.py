"""Infrared emitter platform for IR Learning Hub."""

from __future__ import annotations

from typing import Any

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredDeviceClass,
    InfraredEmitterEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_IEEE, DOMAIN
from .ir_command import command_send_payload
from .storage import IRRegistryStore, normalize_ieee
from .zha_adapter import ZHAAdapter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the IR Learning Hub infrared emitter for one transmitter entry."""
    domain_data = hass.data.get(DOMAIN, {})
    store: IRRegistryStore | None = domain_data.get("store")
    adapter: ZHAAdapter | None = domain_data.get("adapter")
    if store is None or adapter is None:
        async_add_entities([])
        return

    transmitter_id = normalize_ieee(entry.data[CONF_IEEE])
    async_add_entities(
        [IRLearningHubInfraredEmitter(store, adapter, transmitter_id, entry.data)]
    )


class IRLearningHubInfraredEmitter(InfraredEmitterEntity):
    """Infrared emitter entity representing one TS1201/Zosung transmitter."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = InfraredDeviceClass.EMITTER
    _attr_should_poll = False

    def __init__(
        self,
        store: IRRegistryStore,
        adapter: ZHAAdapter,
        transmitter_id: str,
        entry_data: dict[str, Any],
    ) -> None:
        """Initialize the emitter."""
        self._store = store
        self._adapter = adapter
        self._transmitter_id = transmitter_id
        self._entry_data = entry_data
        self._attr_unique_id = transmitter_id
        self._attr_device_info = _transmitter_device_info(transmitter_id, entry_data)

    async def async_send_command(self, command: InfraredCommand) -> None:
        """Send an opaque Zosung command through the configured transmitter."""
        transmitter = self._store.resolve_transmitter(self._transmitter_id)
        try:
            transmitter, code = command_send_payload(transmitter, command)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        await self._adapter.async_send(transmitter, code)


def _transmitter_device_info(
    transmitter_id: str,
    entry_data: dict[str, Any],
) -> DeviceInfo:
    """Return device registry info for the IR Learning Hub emitter."""
    return DeviceInfo(identifiers={(DOMAIN, transmitter_id)})
