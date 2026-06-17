"""Switch consumer entities for IR Learning Hub."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .consumer import (
    ConsumerEntityManager,
    RegistryBackedConsumerEntity,
    async_setup_consumer_platform,
)
from .registry_runtime import EntitySpec
from .storage import IRRegistryStore

SWITCH_DOMAIN = "switch"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up registry-backed switch entities for the owner entry."""
    await async_setup_consumer_platform(
        hass,
        entry,
        async_add_entities,
        manager_key="switch_manager",
        platform_domain=SWITCH_DOMAIN,
        entity_factory=IRLearningHubSwitchEntity,
    )


class IRLearningHubSwitchEntity(RegistryBackedConsumerEntity, SwitchEntity, RestoreEntity):
    """Switch entity backed by stored IR commands."""

    def __init__(
        self,
        store: IRRegistryStore,
        spec: EntitySpec,
    ) -> None:
        """Initialize the switch."""
        self._is_on = False
        super().__init__(store, spec)

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is not None:
            self._is_on = state.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Return the assumed on/off state."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._send_power_command("power_on", "power_toggle")
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._send_power_command("power_off", "power_toggle")
        self._is_on = False
        self.async_write_ha_state()

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the switch."""
        if "power_toggle" in self._spec.command_keys:
            await self.async_send_stored_command("power_toggle")
            self._is_on = not self._is_on
        elif self._is_on:
            await self._send_power_command("power_off")
            self._is_on = False
        else:
            await self._send_power_command("power_on")
            self._is_on = True
        self.async_write_ha_state()

    async def _send_power_command(self, *command_ids: str) -> None:
        for command_id in command_ids:
            if command_id in self._spec.command_keys:
                await self.async_send_stored_command(command_id)
                return
        raise ServiceValidationError(
            f"IR device {self._spec.device_identifier} has no supported power command"
        )


class SwitchEntityManager(ConsumerEntityManager):
    """Runtime materializer for switch entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: IRRegistryStore,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize the switch manager."""
        super().__init__(
            hass,
            store,
            async_add_entities,
            SWITCH_DOMAIN,
            IRLearningHubSwitchEntity,
        )
