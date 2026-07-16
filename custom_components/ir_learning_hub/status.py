"""Shared status state for IR Learning Hub."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .const import STATUS_IDLE


@dataclass
class HubStatus:
    """Mutable status state observed by the status sensor."""

    state: str = STATUS_IDLE
    last_action: str | None = None
    last_location_id: str | None = None
    last_ir_device_id: str | None = None
    last_command_id: str | None = None
    last_error: str | None = None
    last_error_message: str | None = None
    last_updated: str | None = None
    last_request_id: str | None = None
    last_dispatch_status: str | None = None
    last_transmitter_id: str | None = None
    last_queue_wait_ms: int | None = None
    last_command_age_ms: int | None = None
    last_queue_depth: int | None = None
    delivery_confirmed: bool | None = None
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    @callback
    def async_subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to status changes."""
        self._listeners.append(listener)

        @callback
        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @callback
    def async_set(
        self,
        state: str,
        *,
        action: str | None = None,
        location_id: str | None = None,
        ir_device_id: str | None = None,
        command_id: str | None = None,
        error: str | None = None,
        error_message: str | None = None,
        request_id: str | None = None,
        dispatch_status: str | None = None,
        transmitter_id: str | None = None,
        queue_wait_ms: int | None = None,
        command_age_ms: int | None = None,
        queue_depth: int | None = None,
        delivery_confirmed: bool | None = None,
    ) -> None:
        """Update status and notify listeners."""
        self.state = state
        self.last_action = action
        self.last_location_id = location_id
        self.last_ir_device_id = ir_device_id
        self.last_command_id = command_id
        self.last_error = error
        self.last_error_message = error_message
        self.last_updated = dt_util.utcnow().isoformat()
        self.last_request_id = request_id
        self.last_dispatch_status = dispatch_status
        self.last_transmitter_id = transmitter_id
        self.last_queue_wait_ms = queue_wait_ms
        self.last_command_age_ms = command_age_ms
        self.last_queue_depth = queue_depth
        self.delivery_confirmed = delivery_confirmed

        for listener in list(self._listeners):
            listener()

    @property
    def attributes(self) -> dict[str, str | None]:
        """Return sensor attributes."""
        return {
            "last_action": self.last_action,
            "last_location_id": self.last_location_id,
            "last_ir_device_id": self.last_ir_device_id,
            "last_command_id": self.last_command_id,
            "last_error": self.last_error,
            "last_error_message": self.last_error_message,
            "last_updated": self.last_updated,
            "last_request_id": self.last_request_id,
            "last_dispatch_status": self.last_dispatch_status,
            "last_transmitter_id": self.last_transmitter_id,
            "last_queue_wait_ms": self.last_queue_wait_ms,
            "last_command_age_ms": self.last_command_age_ms,
            "last_queue_depth": self.last_queue_depth,
            "delivery_confirmed": self.delivery_confirmed,
        }
