"""Registry storage for IR Learning Hub."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_FEATURES,
    ERROR_COMMAND_NOT_FOUND,
    ERROR_STORAGE_ERROR,
    ERROR_TRANSMITTER_NOT_CONFIGURED,
    ERROR_TRANSMITTER_REQUIRED,
    ERROR_TRANSMITTER_UNAVAILABLE,
    PREFERRED_DOMAIN_AUTO,
    PREFERRED_DOMAINS,
    SIGNAL_REGISTRY_UPDATED,
)
from .device_profiles import get_profile
from .errors import IRLearningHubError
from .storage_migration import migrate_to_v4
from .transmitter_identity import normalize_transmitter_ref

STORAGE_KEY = "ir_learning_hub"
STORAGE_VERSION = 4
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def normalize_ieee(ieee: str) -> str:
    """Normalize IEEE for stable registry keys."""
    return ieee.replace(":", "").lower()


def _default_data() -> dict[str, Any]:
    return {"version": STORAGE_VERSION, "transmitters": {}, "locations": {}}


def _validate_id(value: str, field: str) -> None:
    if not ID_PATTERN.fullmatch(value):
        raise IRLearningHubError(
            ERROR_STORAGE_ERROR,
            f"{field} must match [a-z0-9_]+",
        )


def _validate_preferred_domain(value: str) -> None:
    if value not in PREFERRED_DOMAINS:
        raise IRLearningHubError(
            ERROR_STORAGE_ERROR,
            f"preferred_domain must be one of: {', '.join(PREFERRED_DOMAINS)}",
        )


def _validate_command_feature(value: str) -> None:
    if value not in COMMAND_FEATURES:
        raise IRLearningHubError(
            ERROR_STORAGE_ERROR,
            f"feature must be one of: {', '.join(COMMAND_FEATURES)}",
        )


class IRRegistryDataStore(Store):
    """Store with additive registry migrations."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate old registry data to the current schema."""
        return migrate_to_v4(old_data)


class IRRegistryStore:
    """Store-backed IR command registry."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._hass = hass
        self._store = IRRegistryDataStore(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = _default_data()

    async def async_load(self) -> None:
        """Load registry data."""
        stored = await self._store.async_load()
        if not stored:
            self.data = _default_data()
            return

        if stored.get("version", 1) < STORAGE_VERSION:
            stored = migrate_to_v4(stored)

        self.data = _default_data() | stored
        self.data.setdefault("transmitters", {})
        self.data.setdefault("locations", {})

    async def async_save(self) -> None:
        """Persist registry data."""
        await self._store.async_save(self.data)
        async_dispatcher_send(self._hass, SIGNAL_REGISTRY_UPDATED)

    async def async_upsert_transmitter_from_entry(self, entry_data: dict[str, Any]) -> str:
        """Ensure the configured transmitter exists in registry storage."""
        ieee = entry_data["ieee"]
        transmitter_id = normalize_ieee(ieee)
        profile_id = entry_data.get("profile", "ts1201_zosung")
        profile = get_profile(profile_id)
        existing = self.data["transmitters"].get(transmitter_id, {})
        updated = {
            "ieee": ieee,
            "name": existing.get("name") or f"IR transmitter {ieee}",
            "manufacturer": existing.get("manufacturer"),
            "model": existing.get("model"),
            "quirk_class": existing.get("quirk_class"),
            "profile": profile_id,
            "config": {
                "endpoint_id": entry_data.get("endpoint_id", profile["endpoint_id"]),
                "ir_control_cluster": entry_data.get(
                    "cluster_id", profile["ir_control_cluster"]
                ),
                "ir_transmit_cluster": profile["ir_transmit_cluster"],
                "learn_timeout": entry_data.get(
                    "learn_timeout", profile["learning_timeout"]
                ),
                "learn_reassert_interval": entry_data.get(
                    "learn_reassert_interval", profile["learn_reassert_interval"]
                ),
            },
            "enabled": existing.get("enabled", True),
            "needs_confirmation": existing.get("needs_confirmation", False),
        }
        if existing == updated:
            return transmitter_id
        self.data["transmitters"][transmitter_id] = updated
        await self.async_save()
        return transmitter_id

    async def async_reconcile_transmitters(self, valid_keys: set[str]) -> None:
        """Drop orphaned transmitters that no longer have a config entry."""
        if not valid_keys:
            return
        transmitters = self.data.setdefault("transmitters", {})
        stale_keys = [key for key in transmitters if key not in valid_keys]
        if not stale_keys:
            return
        for key in stale_keys:
            transmitters.pop(key, None)
        await self.async_save()

    def resolve_transmitter(self, transmitter_id: str | None = None) -> dict[str, Any]:
        """Resolve an explicit or default enabled transmitter."""
        transmitters = self.data.get("transmitters", {})
        if transmitter_id:
            transmitter = transmitters.get(transmitter_id)
            if transmitter and transmitter.get("enabled", True):
                return transmitter
            raise IRLearningHubError(
                ERROR_TRANSMITTER_UNAVAILABLE,
                f"Transmitter {transmitter_id} is not available",
            )

        enabled = [item for item in transmitters.values() if item.get("enabled", True)]
        if not enabled:
            raise IRLearningHubError(
                ERROR_TRANSMITTER_NOT_CONFIGURED,
                "No enabled IR transmitter is configured",
            )
        if len(enabled) > 1:
            raise IRLearningHubError(
                ERROR_TRANSMITTER_REQUIRED,
                "More than one transmitter is enabled; pass transmitter_id",
            )
        return enabled[0]

    async def add_location(self, location_id: str, name: str) -> None:
        """Add or update a location."""
        _validate_id(location_id, "location_id")
        location = self.data["locations"].setdefault(
            location_id, {"name": name, "devices": {}}
        )
        location["name"] = name
        await self.async_save()

    async def rename_location(self, location_id: str, name: str) -> None:
        """Rename a location."""
        self._location(location_id)["name"] = name
        await self.async_save()

    async def delete_location(self, location_id: str, confirm: bool) -> None:
        """Delete a location and nested devices."""
        if not confirm:
            raise IRLearningHubError(
                ERROR_STORAGE_ERROR,
                "delete_location requires confirm: true",
            )
        self._location(location_id)
        self.data["locations"].pop(location_id)
        await self.async_save()

    async def add_device(
        self,
        location_id: str,
        ir_device_id: str,
        name: str,
        device_type: str,
        preferred_domain: str | None = None,
        transmitter_id: str | None = None,
    ) -> None:
        """Add or update an IR device."""
        _validate_id(location_id, "location_id")
        _validate_id(ir_device_id, "ir_device_id")
        if preferred_domain is not None:
            _validate_preferred_domain(preferred_domain)
        if transmitter_id:
            self._validate_transmitter_id(transmitter_id)
        location = self.data["locations"].setdefault(
            location_id, {"name": location_id, "devices": {}}
        )
        device = location["devices"].setdefault(
            ir_device_id,
            {
                "name": name,
                "type": device_type,
                "preferred_domain": preferred_domain or PREFERRED_DOMAIN_AUTO,
                "transmitter_id": transmitter_id,
                "commands": {},
            },
        )
        device["name"] = name
        device["type"] = device_type
        device.setdefault("preferred_domain", PREFERRED_DOMAIN_AUTO)
        device.setdefault("transmitter_id", None)
        if preferred_domain is not None:
            device["preferred_domain"] = preferred_domain
        if transmitter_id is not None:
            if transmitter_id:
                self._validate_transmitter_id(transmitter_id)
            device["transmitter_id"] = transmitter_id or None
        await self.async_save()

    async def rename_device(self, location_id: str, ir_device_id: str, name: str) -> None:
        """Rename an IR device."""
        self._device(location_id, ir_device_id)["name"] = name
        await self.async_save()

    async def update_device(
        self,
        location_id: str,
        ir_device_id: str,
        *,
        name: str | None = None,
        device_type: str | None = None,
        preferred_domain: str | None = None,
        transmitter_id: str | None = None,
    ) -> None:
        """Update an IR device's metadata."""
        device = self._device(location_id, ir_device_id)
        if name is not None:
            device["name"] = name
        if device_type is not None:
            device["type"] = device_type
        if preferred_domain is not None:
            _validate_preferred_domain(preferred_domain)
            device["preferred_domain"] = preferred_domain
        if transmitter_id is not None:
            if transmitter_id:
                self._validate_transmitter_id(transmitter_id)
            device["transmitter_id"] = transmitter_id or None
        await self.async_save()

    async def delete_device(
        self, location_id: str, ir_device_id: str, confirm: bool
    ) -> None:
        """Delete an IR device and nested commands."""
        if not confirm:
            raise IRLearningHubError(
                ERROR_STORAGE_ERROR,
                "delete_device requires confirm: true",
            )
        self._device(location_id, ir_device_id)
        self._location(location_id)["devices"].pop(ir_device_id)
        await self.async_save()

    async def add_command(
        self,
        location_id: str,
        ir_device_id: str,
        command_id: str,
        name: str,
        feature: str | None = None,
    ) -> None:
        """Add an empty command placeholder."""
        _validate_id(command_id, "command_id")
        device = self._device(location_id, ir_device_id)
        command = device["commands"].setdefault(command_id, {})
        command.setdefault("code", "")
        command.setdefault("format", "zosung_base64")
        command.setdefault("verified", False)
        command["name"] = name
        if feature is not None:
            if feature:
                _validate_command_feature(feature)
                command["feature"] = feature
            else:
                command.pop("feature", None)
        command["updated_at"] = dt_util.utcnow().isoformat()
        await self.async_save()

    async def rename_command(
        self, location_id: str, ir_device_id: str, command_id: str, name: str
    ) -> None:
        """Rename a command."""
        self._command(location_id, ir_device_id, command_id)["name"] = name
        await self.async_save()

    async def delete_command(
        self, location_id: str, ir_device_id: str, command_id: str
    ) -> None:
        """Delete a command."""
        self._command(location_id, ir_device_id, command_id)
        self._device(location_id, ir_device_id)["commands"].pop(command_id)
        await self.async_save()

    async def save_command(
        self,
        location_id: str,
        ir_device_id: str,
        command_id: str,
        name: str,
        code: str,
        verified: bool,
        code_format: str = "zosung_base64",
        source: dict[str, Any] | None = None,
        feature: str | None = None,
    ) -> None:
        """Upsert a learned or generated command.

        ``source`` is optional provenance for non-learned commands (e.g. a
        protocol generator or a future importer). It is stored verbatim and never
        used on the send path; the transmitter always sends ``code``.
        """
        if not code:
            raise IRLearningHubError(ERROR_STORAGE_ERROR, "code must not be empty")
        _validate_id(location_id, "location_id")
        _validate_id(ir_device_id, "ir_device_id")
        _validate_id(command_id, "command_id")

        location = self.data["locations"].setdefault(
            location_id, {"name": location_id, "devices": {}}
        )
        device = location["devices"].setdefault(
            ir_device_id,
            {
                "name": ir_device_id,
                "type": "generic",
                "preferred_domain": PREFERRED_DOMAIN_AUTO,
                "transmitter_id": None,
                "commands": {},
            },
        )
        existing = device["commands"].get(command_id, {})
        command = {
            "name": name,
            "code": code,
            "format": code_format,
            "verified": verified,
            "updated_at": dt_util.utcnow().isoformat(),
        }
        if existing.get("icon"):
            command["icon"] = existing["icon"]
        if feature is None:
            if existing.get("feature"):
                command["feature"] = existing["feature"]
        elif feature:
            _validate_command_feature(feature)
            command["feature"] = feature
        if source is not None:
            command["source"] = source
        device["commands"][command_id] = command
        await self.async_save()

    async def update_command(
        self,
        location_id: str,
        ir_device_id: str,
        command_id: str,
        name: str | None = None,
        icon: str | None = None,
        feature: str | None = None,
    ) -> None:
        """Update a command's name and/or icon without re-learning its code."""
        command = self._command(location_id, ir_device_id, command_id)
        if name is not None:
            command["name"] = name
        if icon is not None:
            if icon:
                command["icon"] = icon
            else:
                command.pop("icon", None)
        if feature is not None:
            if feature:
                _validate_command_feature(feature)
                command["feature"] = feature
            else:
                command.pop("feature", None)
        command["updated_at"] = dt_util.utcnow().isoformat()
        await self.async_save()

    def get_command(self, location_id: str, ir_device_id: str, command_id: str) -> dict:
        """Return a saved command."""
        return self._command(location_id, ir_device_id, command_id)

    def list_commands(self) -> dict[str, Any]:
        """Return a response-safe registry copy."""
        transmitters = [
            {
                "key": transmitter_id,
                "ieee": item.get("ieee"),
                "name": item.get("name"),
                "enabled": item.get("enabled", True),
            }
            for transmitter_id, item in sorted(
                self.data.get("transmitters", {}).items()
            )
        ]
        return {
            "locations": deepcopy(self.data.get("locations", {})),
            "transmitters": transmitters,
        }

    def _location(self, location_id: str) -> dict[str, Any]:
        try:
            return self.data["locations"][location_id]
        except KeyError as err:
            raise IRLearningHubError(
                ERROR_COMMAND_NOT_FOUND,
                f"Location {location_id} was not found",
            ) from err

    def _device(self, location_id: str, ir_device_id: str) -> dict[str, Any]:
        try:
            return self._location(location_id)["devices"][ir_device_id]
        except KeyError as err:
            raise IRLearningHubError(
                ERROR_COMMAND_NOT_FOUND,
                f"IR device {ir_device_id} was not found",
            ) from err

    def _command(
        self, location_id: str, ir_device_id: str, command_id: str
    ) -> dict[str, Any]:
        try:
            return self._device(location_id, ir_device_id)["commands"][command_id]
        except KeyError as err:
            raise IRLearningHubError(
                ERROR_COMMAND_NOT_FOUND,
                f"Command {command_id} was not found",
            ) from err

    def _validate_transmitter_id(self, transmitter_id: str) -> None:
        """Ensure a stored device transmitter id is already canonical and known."""
        if normalize_transmitter_ref(transmitter_id) != transmitter_id:
            raise IRLearningHubError(
                ERROR_TRANSMITTER_UNAVAILABLE,
                f"Unknown IR transmitter: {transmitter_id}",
            )
        if transmitter_id not in self.data.get("transmitters", {}):
            raise IRLearningHubError(
                ERROR_TRANSMITTER_UNAVAILABLE,
                f"Unknown IR transmitter: {transmitter_id}",
            )
