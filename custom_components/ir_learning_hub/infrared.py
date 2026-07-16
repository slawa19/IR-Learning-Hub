"""Infrared emitter platform for IR Learning Hub."""

from __future__ import annotations

import logging
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

from .const import CONF_IEEE, DOMAIN, TRANSMITTER_SUBENTRY_TYPE
from .dispatcher import CommandContext, IRCommandDispatcher
from .ir_command import command_send_payload
from .storage import IRRegistryStore, normalize_ieee

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up IR Learning Hub infrared emitters for transmitter subentries."""
    domain_data = hass.data.get(DOMAIN, {})
    store: IRRegistryStore | None = domain_data.get("store")
    dispatcher: IRCommandDispatcher | None = domain_data.get("dispatcher")
    if store is None or dispatcher is None:
        async_add_entities([])
        return

    for subentry in entry.get_subentries_of_type(TRANSMITTER_SUBENTRY_TYPE):
        transmitter_id = normalize_ieee(subentry.data[CONF_IEEE])
        async_add_entities(
            [
                IRLearningHubInfraredEmitter(
                    store,
                    dispatcher,
                    transmitter_id,
                    dict(subentry.data),
                )
            ],
            config_subentry_id=subentry.subentry_id,
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
        dispatcher: IRCommandDispatcher,
        transmitter_id: str,
        entry_data: dict[str, Any],
    ) -> None:
        """Initialize the emitter."""
        self._store = store
        self._dispatcher = dispatcher
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

        await self._dispatcher.async_send(
            self._transmitter_id,
            transmitter,
            code,
            context=CommandContext(
                request_id=getattr(command, "request_id", None) or _new_request_id(),
                transmitter_id=self._transmitter_id,
                location_id=getattr(command, "location_id", None),
                ir_device_id=getattr(command, "ir_device_id", None),
                command_id=getattr(command, "command_id", None),
                source="entity",
            ),
        )
        _LOGGER.debug(
            "IR send dispatched to ZHA (delivery not confirmed): transmitter=%s code_len=%s",
            transmitter.get("ieee"),
            len(code),
        )


def _transmitter_device_info(
    transmitter_id: str,
    entry_data: dict[str, Any],
) -> DeviceInfo:
    """Return device registry info for the IR Learning Hub emitter."""
    return DeviceInfo(identifiers={(DOMAIN, transmitter_id)})


def _new_request_id() -> str:
    from uuid import uuid4

    return uuid4().hex
