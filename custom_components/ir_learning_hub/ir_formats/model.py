"""Normalized IR signal model shared by every format converter."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CARRIER_HZ = 38000
_UINT16_MAX = 0xFFFF


class IRFormatError(ValueError):
    """Raised when an IR signal or an encoded payload is malformed."""


@dataclass
class IRSignal:
    """A transport-agnostic IR signal.

    ``timings`` is a list of alternating mark/space durations in microseconds,
    starting with a mark. Any frame repeats and inter-frame gaps are already
    expanded into this list, because the transmitter sends exactly one continuous
    burst list per command -- "repeat" is not a separate field the hardware
    understands.

    ``carrier_frequency`` is informational. The Tuya/Zosung payload does not
    carry it (the TS1201 transmits at a fixed ~38 kHz), but converters keep it so
    a caller can warn when an imported code expects a very different carrier.
    """

    timings: list[int] = field(default_factory=list)
    carrier_frequency: int = DEFAULT_CARRIER_HZ

    def __post_init__(self) -> None:
        self.timings = [self._validate_timing(value) for value in self.timings]
        if not self.timings:
            raise IRFormatError("IR signal must have at least one timing")
        if not isinstance(self.carrier_frequency, int) or self.carrier_frequency <= 0:
            raise IRFormatError("carrier_frequency must be a positive integer")

    @staticmethod
    def _validate_timing(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise IRFormatError(f"timing must be an integer, got {value!r}")
        if value <= 0:
            raise IRFormatError(f"timing must be positive, got {value}")
        if value > _UINT16_MAX:
            raise IRFormatError(
                f"timing {value} µs does not fit in the 16-bit Zosung payload "
                f"(max {_UINT16_MAX})"
            )
        return value
