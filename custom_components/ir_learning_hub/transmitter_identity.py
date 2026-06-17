"""Helpers for canonical IR transmitter identity handling."""

from __future__ import annotations


def normalize_transmitter_ref(ref: str) -> str:
    """Normalize a transmitter reference candidate to the canonical key shape."""
    normalized = str(ref).strip().lower()
    if "." in normalized:
        normalized = normalized.split(".")[-1]
    if normalized.startswith("ir_transmitter_"):
        normalized = normalized.removeprefix("ir_transmitter_")
    return normalized.replace(":", "").replace("_", "")


def canonical_emitter_entity_id(transmitter_id: str) -> str:
    """Return the default infrared entity_id shape for a canonical transmitter id."""
    chunks = [
        transmitter_id[index : index + 2]
        for index in range(0, len(transmitter_id), 2)
    ]
    return f"infrared.ir_transmitter_{'_'.join(chunks)}"
