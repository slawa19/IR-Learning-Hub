"""Sony SIRC protocol generator.

Sony SIRC encodes a command and a device (address) as a pulse-distance signal
that is LSB-first and transmitted at a 40 kHz carrier. A single frame is not
reliably recognized; the protocol requires the frame to be repeated (>= 3 times)
with a fixed 45 ms frame period. This generator therefore returns the **full**
repeated signal with inter-frame gaps already expanded into the timings, because
the TS1201 sends one continuous burst list per command.

Frame layout (microseconds):

    header:  2400 mark, 600 space
    bit 0:    600 mark, 600 space
    bit 1:   1200 mark, 600 space

Bit stream (LSB first):

    SIRC-12: 7 command bits + 5 device bits
    SIRC-15: 7 command bits + 8 device bits
    SIRC-20: 7 command bits + 5 device bits + 8 extended bits
"""

from __future__ import annotations

from ..model import IRFormatError, IRSignal

CARRIER_HZ = 40000
UNIT_US = 600
HEADER_MARK_US = 2400
FRAME_PERIOD_US = 45000
DEFAULT_REPEATS = 3
# Sony needs >= 3 frames; an upper bound keeps an accidental huge value from
# expanding into a multi-million entry signal (memory/CPU) inside the caller.
MAX_REPEATS = 20

# bits -> device (address) field width
_DEVICE_WIDTH = {12: 5, 15: 8, 20: 5}
_COMMAND_WIDTH = 7
_EXTENDED_WIDTH = 8


def _lsb_bits(value: int, width: int) -> list[int]:
    return [(value >> i) & 1 for i in range(width)]


def encode_sony_sirc(
    *,
    command: int,
    device: int,
    bits: int = 12,
    extended: int = 0,
    repeats: int = DEFAULT_REPEATS,
    frame_period_us: int = FRAME_PERIOD_US,
    carrier_frequency: int = CARRIER_HZ,
) -> IRSignal:
    """Build the full repeated Sony SIRC signal as an :class:`IRSignal`."""
    if bits not in _DEVICE_WIDTH:
        raise IRFormatError(f"unsupported Sony SIRC bit length: {bits} (use 12/15/20)")
    if not 1 <= repeats <= MAX_REPEATS:
        raise IRFormatError(f"repeats must be 1..{MAX_REPEATS}")
    device_width = _DEVICE_WIDTH[bits]
    _check_range("command", command, _COMMAND_WIDTH)
    _check_range("device", device, device_width)
    if bits == 20:
        _check_range("extended", extended, _EXTENDED_WIDTH)

    stream = _lsb_bits(command, _COMMAND_WIDTH) + _lsb_bits(device, device_width)
    if bits == 20:
        stream += _lsb_bits(extended, _EXTENDED_WIDTH)

    frame: list[int] = [HEADER_MARK_US, UNIT_US]
    for bit in stream:
        frame += [2 * UNIT_US if bit else UNIT_US, UNIT_US]

    # The frame currently ends with a UNIT space. Stretch that trailing space so
    # the whole frame lasts one frame period; concatenating frames then yields the
    # correct inter-frame gap before the next header.
    content_us = sum(frame) - UNIT_US
    trailing_us = frame_period_us - content_us
    if trailing_us < UNIT_US:
        # Frame already longer than the nominal period (very long SIRC-20); fall
        # back to a minimal gap so timings stay well-formed.
        trailing_us = UNIT_US
    frame[-1] = trailing_us

    return IRSignal(timings=frame * repeats, carrier_frequency=carrier_frequency)


def _check_range(name: str, value: int, width: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IRFormatError(f"{name} must be an integer, got {value!r}")
    if not 0 <= value < (1 << width):
        raise IRFormatError(f"{name} must be 0..{(1 << width) - 1} ({width} bits)")
