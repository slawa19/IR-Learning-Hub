"""Pure storage migration helpers for IR Learning Hub."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


STORAGE_VERSION_V2 = 2
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
