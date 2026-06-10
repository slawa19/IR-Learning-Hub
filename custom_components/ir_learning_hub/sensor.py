"""Status sensor for IR Learning Hub."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    STATUS_CODE_RECEIVED,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_LEARNING,
    STATUS_SENDING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the IR Learning Hub status sensor."""
    status = hass.data.get(DOMAIN, {}).get("status")
    if status is None:
        async_add_entities([])
        return
    async_add_entities([IRLearningHubStatusSensor(status, entry.entry_id)])


class IRLearningHubStatusSensor(SensorEntity):
    """Diagnostic status sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        STATUS_IDLE,
        STATUS_LEARNING,
        STATUS_SENDING,
        STATUS_CODE_RECEIVED,
        STATUS_ERROR,
    ]
    _attr_icon = "mdi:remote"

    def __init__(self, status, entry_id: str) -> None:
        """Initialize the sensor."""
        self._status = status
        self._attr_unique_id = f"{entry_id}_ir_learning_hub_status"
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to status changes."""
        self._unsubscribe = self._status.async_subscribe(self._handle_status_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from status changes."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    @property
    def native_value(self) -> str:
        """Return current status."""
        return self._status.state

    @property
    def extra_state_attributes(self) -> dict:
        """Return status attributes."""
        return self._status.attributes

    @callback
    def _handle_status_update(self) -> None:
        self.async_write_ha_state()
