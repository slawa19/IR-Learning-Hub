"""Transport-agnostic IR format layer.

This package is intentionally free of any Home Assistant imports so it can be
unit-tested in isolation and reused by every future code source.

The architecture is a small pipeline:

    source (protocol generator / importer)
        -> IRSignal (normalized raw timings)
        -> zosung.encode -> zosung_base64 (the payload the TS1201 actually sends)

Today the only source is the Sony SIRC protocol generator. Future work
(Pronto Hex, raw timings, LIRC; see docs/FEATURE-IR-FORMAT-CONVERTERS.md) plugs
in as additional sources that all produce an ``IRSignal`` and reuse the same
``zosung`` codec, so nothing below has to change to support them.
"""

from __future__ import annotations

from .model import DEFAULT_CARRIER_HZ, IRFormatError, IRSignal
from .protocols import generate as generate_protocol
from .protocols import list_protocols
from .zosung import decode as zosung_decode
from .zosung import encode as zosung_encode

__all__ = [
    "DEFAULT_CARRIER_HZ",
    "IRFormatError",
    "IRSignal",
    "generate_protocol",
    "list_protocols",
    "zosung_decode",
    "zosung_encode",
]
