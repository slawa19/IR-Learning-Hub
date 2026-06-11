"""Protocol generators: (device, command) -> IRSignal.

Each generator turns a protocol-level description into fully expanded raw
timings. New protocols (NEC, RC5, ...) register here and automatically become
available to the ``generate`` dispatcher and the ``generate_code`` service.
"""

from __future__ import annotations

from typing import Any, Callable

from ..model import IRFormatError, IRSignal
from .sony_sirc import encode_sony_sirc

_GENERATORS: dict[str, Callable[..., IRSignal]] = {
    "sony_sirc": encode_sony_sirc,
}


def list_protocols() -> list[str]:
    """Return the registered protocol names."""
    return sorted(_GENERATORS)


def generate(protocol: str, params: dict[str, Any]) -> IRSignal:
    """Generate an :class:`IRSignal` for ``protocol`` from ``params``."""
    try:
        generator = _GENERATORS[protocol]
    except KeyError as err:
        raise IRFormatError(f"unknown protocol: {protocol!r}") from err
    try:
        return generator(**params)
    except TypeError as err:
        # Surfaces unexpected/missing parameters as a clean format error.
        raise IRFormatError(f"invalid parameters for {protocol!r}: {err}") from err
