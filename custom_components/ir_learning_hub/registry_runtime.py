"""Pure registry-to-entity projection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from .capabilities import DeviceCapabilities, infer_capabilities, normalize_command_id
except ImportError:  # pragma: no cover - supports standalone unittest imports.
    from capabilities import DeviceCapabilities, infer_capabilities, normalize_command_id

DOMAIN_MEDIA_PLAYER = "media_player"
DOMAIN_REMOTE = "remote"
DOMAIN_SWITCH = "switch"
PREFERRED_DOMAIN_AUTO = "auto"


@dataclass(frozen=True)
class EntitySpec:
    """Desired HA entity derived from one stored IR device."""

    domain: str
    unique_id: str
    location_id: str
    ir_device_id: str
    name: str
    transmitter_id: str | None
    command_ids: tuple[str, ...]
    command_keys: dict[str, str]
    capabilities: DeviceCapabilities

    @property
    def device_identifier(self) -> str:
        """Return the virtual HA device identifier."""
        return f"{self.location_id}__{self.ir_device_id}"


def desired_entities(store_data: dict[str, Any]) -> list[EntitySpec]:
    """Return the consumer entities that should exist for registry data."""
    specs: list[EntitySpec] = []
    for location_id, location in sorted(store_data.get("locations", {}).items()):
        devices = location.get("devices", {})
        for ir_device_id, device in sorted(devices.items()):
            commands = device.get("commands", {})
            command_keys = _command_keys(commands)
            capabilities = infer_capabilities(tuple(command_keys))
            domain = _select_domain(
                str(device.get("preferred_domain") or PREFERRED_DOMAIN_AUTO),
                str(device.get("type") or "generic"),
                capabilities,
            )
            if domain is None:
                continue
            suffix = "__switch" if domain == DOMAIN_SWITCH else ""
            unique_id = f"{location_id}__{ir_device_id}{suffix}"
            specs.append(
                EntitySpec(
                    domain=domain,
                    unique_id=unique_id,
                    location_id=location_id,
                    ir_device_id=ir_device_id,
                    name=str(device.get("name") or ir_device_id),
                    transmitter_id=device.get("transmitter_id") or None,
                    command_ids=tuple(sorted(command_keys)),
                    command_keys=command_keys,
                    capabilities=capabilities,
                )
            )
    return specs


def desired_entities_for_domain(
    store_data: dict[str, Any],
    domain: str,
) -> dict[str, EntitySpec]:
    """Return desired entities for one HA domain keyed by unique_id."""
    return {
        spec.unique_id: spec
        for spec in desired_entities(store_data)
        if spec.domain == domain
    }


def diff_entity_ids(
    current_unique_ids: set[str],
    desired: dict[str, EntitySpec],
) -> tuple[set[str], set[str]]:
    """Return unique IDs to add and remove for one platform."""
    desired_unique_ids = set(desired)
    return desired_unique_ids - current_unique_ids, current_unique_ids - desired_unique_ids


def _command_keys(commands: dict[str, Any]) -> dict[str, str]:
    keys: dict[str, str] = {}
    for stored_id in commands:
        canonical_id = normalize_command_id(stored_id)
        keys.setdefault(canonical_id, stored_id)
    return keys


def _select_domain(
    preferred_domain: str,
    device_type: str,
    capabilities: DeviceCapabilities,
) -> str | None:
    if preferred_domain == DOMAIN_SWITCH:
        return DOMAIN_SWITCH if capabilities.is_pure_switch else DOMAIN_REMOTE
    if preferred_domain in {DOMAIN_MEDIA_PLAYER, DOMAIN_REMOTE}:
        return preferred_domain

    if device_type == DOMAIN_MEDIA_PLAYER:
        return DOMAIN_MEDIA_PLAYER
    if device_type == DOMAIN_SWITCH and capabilities.is_pure_switch:
        return DOMAIN_SWITCH
    return DOMAIN_REMOTE
