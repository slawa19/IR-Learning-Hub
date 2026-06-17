"""Pure storage migration helpers for IR Learning Hub."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from .capabilities import seed_feature_from_command_id
except ImportError:  # pragma: no cover - supports standalone unittest imports.
    from capabilities import seed_feature_from_command_id

STORAGE_VERSION_V2 = 2
STORAGE_VERSION_V3 = 3
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
