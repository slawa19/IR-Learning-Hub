"""Infrared command wrappers for IR Learning Hub."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from infrared_protocols.commands import Command as InfraredCommand


DEFAULT_MODULATION = 38000
ZOSUNG_FORMAT = "zosung_base64"


class ZosungCommand(InfraredCommand):
    """Opaque Zosung IR command carried through the HA infrared platform."""

    def __init__(
        self,
        code: str,
        *,
        command_format: str = ZOSUNG_FORMAT,
        modulation: int = DEFAULT_MODULATION,
        repeat_count: int = 0,
        location_id: str | None = None,
        ir_device_id: str | None = None,
        command_id: str | None = None,
    ) -> None:
        """Initialize the command."""
        super().__init__(modulation=modulation, repeat_count=repeat_count)
        self.code = code
        self.format = command_format
        self.location_id = location_id
        self.ir_device_id = ir_device_id
        self.command_id = command_id

    def get_raw_timings(self) -> list[int]:
        """Return raw timings.

        Zosung payloads are opaque in v1. The IR Learning Hub emitter consumes
        ``code`` directly and therefore never needs raw timings on its send path.
        """
        raise NotImplementedError("ZosungCommand does not expose raw timings")


def command_code(command: InfraredCommand) -> str:
    """Return the opaque sendable code carried by a command."""
    code = getattr(command, "code", None)
    if not isinstance(code, str) or not code:
        raise ValueError("IR command must carry a non-empty code")
    return code


def command_send_payload(
    transmitter: Mapping[str, Any],
    command: InfraredCommand,
) -> tuple[Mapping[str, Any], str]:
    """Return the transmitter and opaque code needed by the ZHA adapter."""
    return transmitter, command_code(command)
