"""Shared consumer entity helpers for IR Learning Hub."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import infrared
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_REGISTRY_UPDATED
from .errors import IRLearningHubError
from .ir_command import ZosungCommand
from .registry_runtime import EntitySpec, desired_entities_for_domain
from .storage import IRRegistryStore, normalize_ieee

INFRARED_DOMAIN = "infrared"
_LOGGER = logging.getLogger(__name__)


EntityFactory = Callable[[IRRegistryStore, EntitySpec], Entity]


async def async_setup_consumer_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    *,
    manager_key: str,
    platform_domain: str,
    entity_factory: EntityFactory,
) -> None:
    """Set up one registry-backed consumer platform for the hub entry."""
    domain_data = hass.data.get(DOMAIN, {})

    store: IRRegistryStore | None = domain_data.get("store")
    if store is None:
        async_add_entities([])
        return

    manager = ConsumerEntityManager(
        hass,
        store,
        async_add_entities,
        platform_domain,
        entity_factory,
    )
    domain_data[manager_key] = manager
    await manager.async_reconcile()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_REGISTRY_UPDATED,
            manager.async_schedule_reconcile,
        )
    )
    entry.async_on_unload(manager.async_unload)


class ConsumerEntityManager:
    """Runtime materializer for registry-backed consumer entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: IRRegistryStore,
        async_add_entities: AddEntitiesCallback,
        platform_domain: str,
        entity_factory: EntityFactory,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.store = store
        self.async_add_entities = async_add_entities
        self.platform_domain = platform_domain
        self.entity_factory = entity_factory
        self.entities: dict[str, Entity] = {}
        self._reconcile_lock = asyncio.Lock()
        self._reconcile_task: asyncio.Task | None = None
        self._reconcile_pending = False

    @callback
    def async_schedule_reconcile(self) -> None:
        """Schedule an idempotent registry resync."""
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_pending = True
            return
        self._reconcile_task = self.hass.async_create_task(self.async_reconcile())

    async def async_reconcile(self) -> None:
        """Add, update, and remove entities to match registry data."""
        async with self._reconcile_lock:
            while True:
                self._reconcile_pending = False
                desired = desired_entities_for_domain(self.store.data, self.platform_domain)
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
                    self.entity_factory(self.store, desired[unique_id])
                    for unique_id in sorted(add_ids)
                ]
                for entity in new_entities:
                    self.entities[entity.unique_id] = entity
                if new_entities:
                    self.async_add_entities(new_entities)

                if not self._reconcile_pending:
                    break

    @callback
    def async_unload(self) -> None:
        """Forget manager state during platform unload."""
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_task.cancel()
        self._reconcile_task = None
        self._reconcile_pending = False
        self.entities.clear()


class RegistryBackedConsumerEntity:
    """Mixin for consumer entities backed by an IR registry device spec."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, store: IRRegistryStore, spec: EntitySpec) -> None:
        """Initialize the entity."""
        self._store = store
        self.update_spec(spec)

    def update_spec(self, spec: EntitySpec) -> None:
        """Update this entity from a new desired spec."""
        self._spec = spec
        via_transmitter_id = spec_transmitter_device_id(self._store, spec)
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

    @property
    def device_identifier(self) -> str:
        """Return the virtual target device identifier."""
        return self._spec.device_identifier

    async def async_send_stored_command(self, command_id: str) -> None:
        """Send one raw stored IR command through the resolved emitter entity."""
        await async_send_registry_command(
            self.hass,
            self._store,
            self._spec,
            command_id,
            context=self._context,
        )

    async def async_send_feature_command(self, feature: str) -> None:
        """Send the stored command assigned to a feature role."""
        await async_send_feature_command(
            self.hass,
            self._store,
            self._spec,
            feature,
            context=self._context,
        )


async def async_send_registry_command(
    hass: HomeAssistant,
    store: IRRegistryStore,
    spec: EntitySpec,
    command_id: str,
    *,
    context: Any | None = None,
) -> None:
    """Resolve and send a raw registry command through the selected IR emitter."""
    if command_id not in spec.command_ids:
        raise ServiceValidationError(
            f"IR device {spec.device_identifier} has no command_id {command_id}"
        )

    command = store.get_command(
        spec.location_id,
        spec.ir_device_id,
        command_id,
    )
    try:
        transmitter = resolve_spec_transmitter(store, spec)
    except IRLearningHubError as err:
        raise ServiceValidationError(str(err)) from err
    transmitter_id = transmitter_id_for_store_item(store, transmitter)
    emitter_entity = resolve_emitter_entity_id(hass, transmitter_id)
    await infrared.async_send_command(
        hass,
        emitter_entity,
        ZosungCommand(
            command["code"],
            command_format=command.get("format", "zosung_base64"),
        ),
        context=context,
    )


async def async_send_feature_command(
    hass: HomeAssistant,
    store: IRRegistryStore,
    spec: EntitySpec,
    feature: str,
    *,
    context: Any | None = None,
) -> None:
    """Resolve a feature role and send its stored command."""
    stored_command_id = spec.feature_keys.get(feature)
    if stored_command_id is None:
        raise ServiceValidationError(
            f"IR device {spec.device_identifier} has no feature {feature}"
        )
    await async_send_registry_command(
        hass,
        store,
        spec,
        stored_command_id,
        context=context,
    )


def resolve_spec_transmitter(store: IRRegistryStore, spec: EntitySpec) -> dict[str, Any]:
    """Resolve the transmitter for a spec."""
    if spec.transmitter_id is None:
        return store.resolve_transmitter(None)
    return store.resolve_transmitter(spec.transmitter_id)


def spec_transmitter_device_id(
    store: IRRegistryStore,
    spec: EntitySpec,
) -> str | None:
    """Return the resolved transmitter device identifier for DeviceInfo."""
    try:
        return transmitter_id_for_store_item(store, resolve_spec_transmitter(store, spec))
    except (IRLearningHubError, ServiceValidationError) as err:
        _LOGGER.warning(
            "Could not resolve transmitter device for %s: %s",
            spec.device_identifier,
            err,
        )
        return None


def transmitter_id_for_store_item(
    store: IRRegistryStore,
    transmitter: dict[str, Any],
) -> str:
    """Return the registry transmitter id for a resolved transmitter object."""
    transmitter_ieee = transmitter.get("ieee")
    normalized_ieee = (
        normalize_ieee(str(transmitter_ieee))
        if transmitter_ieee is not None
        else None
    )
    for transmitter_id, item in store.data.get("transmitters", {}).items():
        item_ieee = item.get("ieee")
        if item is transmitter or (
            normalized_ieee is not None
            and item_ieee is not None
            and normalize_ieee(str(item_ieee)) == normalized_ieee
        ):
            return transmitter_id
    raise ServiceValidationError("Resolved IR transmitter is not present in the registry")


def resolve_emitter_entity_id(hass: HomeAssistant, transmitter_id: str) -> str:
    """Return the infrared emitter entity id for a transmitter id."""
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
    """Remove a stale entity registry entry for a disappeared consumer entity."""
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
