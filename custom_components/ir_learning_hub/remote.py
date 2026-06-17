"""Remote consumer entities for IR Learning Hub."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components import infrared
from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .capabilities import normalize_command_id
from .const import DOMAIN, SIGNAL_REGISTRY_UPDATED
from .ir_command import ZosungCommand
from .registry_runtime import EntitySpec, desired_entities_for_domain
from .storage import IRRegistryStore

REMOTE_DOMAIN = "remote"
INFRARED_DOMAIN = "infrared"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up registry-backed remote entities for the consumer owner entry."""
    domain_data = hass.data.get(DOMAIN, {})
    if domain_data.get("consumer_owner") != entry.entry_id:
        async_add_entities([])
        return

    store: IRRegistryStore | None = domain_data.get("store")
    if store is None:
        async_add_entities([])
        return

    manager = RemoteEntityManager(hass, store, async_add_entities)
    domain_data["remote_manager"] = manager
    await manager.async_reconcile()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_REGISTRY_UPDATED,
            manager.async_schedule_reconcile,
        )
    )
    entry.async_on_unload(manager.async_unload)


class RemoteEntityManager:
    """Runtime materializer for remote entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: IRRegistryStore,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.store = store
        self.async_add_entities = async_add_entities
        self.entities: dict[str, IRLearningHubRemoteEntity] = {}
        self._reconcile_lock = asyncio.Lock()
        self._reconcile_task: asyncio.Task | None = None

    @callback
    def async_schedule_reconcile(self) -> None:
        """Schedule an idempotent registry resync."""
        if self._reconcile_task is not None and not self._reconcile_task.done():
            return
        self._reconcile_task = self.hass.async_create_task(self.async_reconcile())

    async def async_reconcile(self) -> None:
        """Add, update, and remove remote entities to match registry data."""
        async with self._reconcile_lock:
            desired = desired_entities_for_domain(self.store.data, REMOTE_DOMAIN)
            current_unique_ids = set(self.entities)
            add_ids = set(desired) - current_unique_ids
            remove_ids = current_unique_ids - set(desired)

            for unique_id in remove_ids:
                entity = self.entities.pop(unique_id)
                entity_id = entity.entity_id
                device_identifier = entity.device_identifier
                await entity.async_remove()
                _remove_entity_registry_entry(self.hass, entity_id)
                _remove_empty_virtual_device(self.hass, device_identifier)

            for unique_id in current_unique_ids & set(desired):
                self.entities[unique_id].update_spec(desired[unique_id])

            new_entities = [
                IRLearningHubRemoteEntity(self.store, desired[unique_id])
                for unique_id in sorted(add_ids)
            ]
            for entity in new_entities:
                self.entities[entity.unique_id] = entity
            if new_entities:
                self.async_add_entities(new_entities)

    @callback
    def async_unload(self) -> None:
        """Forget manager state during platform unload."""
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_task.cancel()
        self._reconcile_task = None
        self.entities.clear()


class IRLearningHubRemoteEntity(RemoteEntity, RestoreEntity):
    """Remote entity backed by stored IR commands."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(
        self,
        store: IRRegistryStore,
        spec: EntitySpec,
    ) -> None:
        """Initialize the remote."""
        self._store = store
        self._is_on = False
        self.update_spec(spec)

    def update_spec(self, spec: EntitySpec) -> None:
        """Update this entity from a new desired spec."""
        self._spec = spec
        via_transmitter_id = _spec_transmitter_device_id(self._store, spec)
        self._attr_unique_id = spec.unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, spec.device_identifier)},
            via_device=(
                (DOMAIN, via_transmitter_id)
                if via_transmitter_id is not None
                else None
            ),
            name=spec.name,
        )
        if self.entity_id is not None:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Return the assumed power state."""
        return self._is_on

    @property
    def device_identifier(self) -> str:
        """Return the virtual target device identifier."""
        return self._spec.device_identifier

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the remote device on."""
        await self._send_power_command("power_on", "power_toggle")
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the remote device off."""
        await self._send_power_command("power_off", "power_toggle")
        self._is_on = False
        self.async_write_ha_state()

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the remote device."""
        if "power_toggle" in self._spec.command_keys:
            await async_send_registry_command(
                self.hass,
                self._store,
                self._spec,
                "power_toggle",
                context=self._context,
            )
            self._is_on = not self._is_on
        elif self._is_on:
            await self._send_power_command("power_off")
            self._is_on = False
        else:
            await self._send_power_command("power_on")
            self._is_on = True
        self.async_write_ha_state()

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more stored command ids."""
        for command_id in command:
            await async_send_registry_command(
                self.hass,
                self._store,
                self._spec,
                command_id,
                context=self._context,
            )

    async def _send_power_command(self, *command_ids: str) -> None:
        for command_id in command_ids:
            if command_id in self._spec.command_keys:
                await async_send_registry_command(
                    self.hass,
                    self._store,
                    self._spec,
                    command_id,
                    context=self._context,
                )
                return
        raise ServiceValidationError(
            f"IR device {self._spec.device_identifier} has no supported power command"
        )


async def async_send_registry_command(
    hass: HomeAssistant,
    store: IRRegistryStore,
    spec: EntitySpec,
    command_id: str,
    *,
    context: Any | None = None,
) -> None:
    """Resolve and send a registry command through the selected IR emitter."""
    canonical_command_id = normalize_command_id(command_id)
    stored_command_id = spec.command_keys.get(canonical_command_id)
    if stored_command_id is None:
        raise ServiceValidationError(
            f"IR device {spec.device_identifier} has no command_id {command_id}"
        )

    command = store.get_command(
        spec.location_id,
        spec.ir_device_id,
        stored_command_id,
    )
    transmitter = _resolve_spec_transmitter(store, spec)
    transmitter_id = _transmitter_id(store, transmitter)
    emitter_entity_id = _emitter_entity_id(hass, transmitter_id)
    await infrared.async_send_command(
        hass,
        emitter_entity_id,
        ZosungCommand(
            command["code"],
            command_format=command.get("format", "zosung_base64"),
        ),
        context=context,
    )


def _resolve_spec_transmitter(store: IRRegistryStore, spec: EntitySpec) -> dict[str, Any]:
    if spec.transmitter_id is None:
        return store.resolve_transmitter(None)
    try:
        return store.resolve_transmitter(spec.transmitter_id)
    except Exception:
        return store.resolve_transmitter(None)


def _spec_transmitter_device_id(
    store: IRRegistryStore,
    spec: EntitySpec,
) -> str | None:
    try:
        return _transmitter_id(store, _resolve_spec_transmitter(store, spec))
    except Exception:
        return None


def _transmitter_id(store: IRRegistryStore, transmitter: dict[str, Any]) -> str:
    for transmitter_id, item in store.data.get("transmitters", {}).items():
        if item is transmitter or item.get("ieee") == transmitter.get("ieee"):
            return transmitter_id
    raise ServiceValidationError("Resolved IR transmitter is not present in the registry")


def _emitter_entity_id(hass: HomeAssistant, transmitter_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        INFRARED_DOMAIN,
        DOMAIN,
        transmitter_id,
    )
    if entity_id is None:
        raise ServiceValidationError(
            f"Infrared emitter entity for transmitter {transmitter_id} was not found"
        )
    return entity_id


def _remove_entity_registry_entry(
    hass: HomeAssistant,
    entity_id: str | None,
) -> None:
    """Remove a stale entity registry entry for a disappeared remote entity."""
    if entity_id is None:
        return
    ent_reg = er.async_get(hass)
    if ent_reg.async_get(entity_id) is None:
        return
    ent_reg.async_remove(entity_id)


def _remove_empty_virtual_device(
    hass: HomeAssistant,
    device_identifier: str,
) -> None:
    """Remove the virtual IR target device when no entities still point to it."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device({(DOMAIN, device_identifier)})
    if device is None:
        return

    ent_reg = er.async_get(hass)
    if any(entry.device_id == device.id for entry in ent_reg.entities.values()):
        return
    dev_reg.async_remove_device(device.id)
