"""Zosung / Tuya IR payload codec.

The TS1201 learns and sends codes in Tuya's format:

    zosung_base64 = base64( FastLZ-level-1( timings as uint16 little-endian µs ) )

FastLZ level 1 is a byte-aligned LZ77 variant. Decompression handles both the
literal runs and back-references a real (compressed) learned code uses.
Compression here emits literal-only blocks: that is a valid FastLZ-1 stream that
the device decompresses correctly, and it avoids the bug surface of a matcher we
do not need -- IR signals are short, so the size cost is negligible.

Reference for the format:
https://gist.github.com/mildsunrise/1d576669b63a260d2cff35fda63ec0b5

NOTE: ``encode`` output is structurally valid but has not yet been confirmed
byte-for-byte against a physical TS1201. Validate on hardware via ``test_code``
before trusting generated payloads (see docs/FEATURE-IR-FORMAT-CONVERTERS.md).
"""

from __future__ import annotations

import base64
import struct

from .model import DEFAULT_CARRIER_HZ, IRFormatError, IRSignal

_LITERAL_BLOCK_MAX = 32


def _decompress(data: bytes) -> bytes:
    """Inflate a FastLZ-level-1 stream."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        header = data[i]
        i += 1
        length = header >> 5
        ref = header & 0x1F
        if length == 0:
            # Literal run of (ref + 1) bytes.
            run = ref + 1
            if i + run > n:
                raise IRFormatError("truncated literal run in Zosung payload")
            out += data[i : i + run]
            i += run
            continue
        # Back-reference.
        if length == 7:
            if i >= n:
                raise IRFormatError("truncated match length in Zosung payload")
            length += data[i]
            i += 1
        length += 2
        if i >= n:
            raise IRFormatError("truncated match distance in Zosung payload")
        distance = ((ref << 8) | data[i]) + 1
        i += 1
        start = len(out) - distance
        if start < 0:
            raise IRFormatError("invalid back-reference in Zosung payload")
        for k in range(length):
            out.append(out[start + k])
    return bytes(out)


def _compress(data: bytes) -> bytes:
    """Emit a literal-only FastLZ-level-1 stream."""
    out = bytearray()
    for i in range(0, len(data), _LITERAL_BLOCK_MAX):
        chunk = data[i : i + _LITERAL_BLOCK_MAX]
        out.append(len(chunk) - 1)  # top 3 bits zero => literal run of len bytes
        out += chunk
    return bytes(out)


def decode(code: str, carrier_frequency: int = DEFAULT_CARRIER_HZ) -> IRSignal:
    """Decode a zosung_base64 string into an :class:`IRSignal`.

    The carrier is not stored in the payload, so it defaults to the TS1201's
    ~38 kHz unless the caller knows better.
    """
    try:
        raw = base64.b64decode(code, validate=True)
    except (ValueError, base64.binascii.Error) as err:  # type: ignore[attr-defined]
        raise IRFormatError("code is not valid base64") from err
    payload = _decompress(raw)
    if len(payload) % 2:
        raise IRFormatError("decoded Zosung payload has an odd byte length")
    timings = [value for (value,) in struct.iter_unpack("<H", payload)]
    return IRSignal(timings=timings, carrier_frequency=carrier_frequency)


def encode(signal: IRSignal) -> str:
    """Encode an :class:`IRSignal` into a zosung_base64 string."""
    payload = b"".join(struct.pack("<H", value) for value in signal.timings)
    return base64.b64encode(_compress(payload)).decode("ascii")
