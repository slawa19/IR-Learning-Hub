"""Pure storage migration helpers for IR Learning Hub."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from .capabilities import seed_feature_from_command_id
    from .transmitter_identity import normalize_transmitter_ref
except ImportError:  # pragma: no cover - supports standalone unittest imports.
    from capabilities import seed_feature_from_command_id
    from transmitter_identity import normalize_transmitter_ref

STORAGE_VERSION_V2 = 2
STORAGE_VERSION_V3 = 3
STORAGE_VERSION_V4 = 4
DEFAULT_PREFERRED_DOMAIN = "auto"


def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Add v2 device fields without dropping existing registry data."""
    migrated = deepcopy(data)
    migrated["version"] = STORAGE_VERSION_V2
    migrated.setdefault("transmitters", {})
    locations = migrated.setdefault("locations", {})

    for location in locations.values():
        devices = location.setdefault("devices", {})
        for device in devices.values():
            device.setdefault("preferred_domain", DEFAULT_PREFERRED_DOMAIN)
            device.setdefault("transmitter_id", None)
            device.setdefault("commands", {})

    return migrated


def migrate_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Seed explicit command features from legacy command ids when possible."""
    migrated = deepcopy(data)
    migrated["version"] = STORAGE_VERSION_V3
    migrated.setdefault("transmitters", {})
    locations = migrated.setdefault("locations", {})

    for location in locations.values():
        devices = location.setdefault("devices", {})
        for device in devices.values():
            device.setdefault("preferred_domain", DEFAULT_PREFERRED_DOMAIN)
            device.setdefault("transmitter_id", None)
            commands = device.setdefault("commands", {})
            for command_id, command in commands.items():
                if command.get("feature"):
                    continue
                feature = seed_feature_from_command_id(command_id)
                if feature is not None:
                    command["feature"] = feature

    return migrated


def migrate_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate any supported older registry data to v3."""
    version = data.get("version", 1)
    migrated = data
    if version < STORAGE_VERSION_V2:
        migrated = migrate_v1_to_v2(migrated)
    if migrated.get("version", 1) < STORAGE_VERSION_V3:
        migrated = migrate_v2_to_v3(migrated)
    return migrated


def migrate_v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize stored device transmitter references."""
    migrated = deepcopy(data)
    migrated["version"] = STORAGE_VERSION_V4
    transmitters = migrated.setdefault("transmitters", {})
    transmitter_keys = set(transmitters)
    locations = migrated.setdefault("locations", {})

    for location in locations.values():
        devices = location.setdefault("devices", {})
        for device in devices.values():
            transmitter_id = device.get("transmitter_id")
            if not transmitter_id:
                device["transmitter_id"] = None
                continue
            canonical = normalize_transmitter_ref(transmitter_id)
            device["transmitter_id"] = canonical if canonical in transmitter_keys else None

    return migrated


def migrate_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate any supported older registry data to v4."""
    migrated = migrate_to_v3(data)
    if migrated.get("version", 1) < STORAGE_VERSION_V4:
        migrated = migrate_v3_to_v4(migrated)
    return migrated
