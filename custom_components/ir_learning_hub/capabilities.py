"""Pure command capability inference for IR Learning Hub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


COMMAND_FEATURES = (
    "power_on",
    "power_off",
    "power_toggle",
    "play",
    "pause",
    "play_pause_toggle",
    "stop",
    "next",
    "previous",
    "fast_forward",
    "rewind",
    "volume_up",
    "volume_down",
    "mute",
    "unmute",
    "mute_toggle",
    "source",
)
COMMAND_FEATURE_SET = frozenset(COMMAND_FEATURES)

COMMAND_ALIASES: dict[str, str] = {
    "vol_up": "volume_up",
    "vol_down": "volume_down",
    "power": "power_toggle",
    "forward": "fast_forward",
    "backward": "rewind",
    "ok": "select",
    "return": "back",
    "input_tv": "source",
    "input_pc": "source",
}

POWER_FEATURES = frozenset({"power_on", "power_off", "power_toggle"})


@dataclass(frozen=True)
class SourceCommand:
    """A stored command that represents a selectable media source."""

    command_id: str
    name: str


@dataclass(frozen=True)
class DeviceCapabilities:
    """Inferred features for one registry device."""

    features: frozenset[str]
    power_mode: str
    media_features: frozenset[str]
    source_commands: tuple[str, ...]
    source_names: dict[str, str]
    sources: tuple[SourceCommand, ...]
    is_pure_switch: bool

    @property
    def assumed_power(self) -> bool:
        """Return true when power state cannot be known from explicit on/off commands."""
        return self.power_mode == "toggle"


def normalize_command_id(command_id: str) -> str:
    """Normalize a stored command id to the canonical seed vocabulary."""
    return COMMAND_ALIASES.get(command_id, command_id)


def normalize_command_ids(
    command_ids: set[str] | frozenset[str] | list[str] | tuple[str, ...],
) -> frozenset[str]:
    """Normalize a collection of command ids for migration seeding only."""
    return frozenset(normalize_command_id(command_id) for command_id in command_ids)


def seed_feature_from_command_id(command_id: str) -> str | None:
    """Infer an initial feature from a legacy command id, if it is canonical."""
    normalized = normalize_command_id(command_id)
    if normalized.startswith("source_"):
        return "source"
    if normalized in COMMAND_FEATURE_SET:
        return normalized
    return None


def infer_capabilities(commands: Iterable[dict[str, Any] | tuple[str, str | None, str | None]]) -> DeviceCapabilities:
    """Infer device capabilities from explicit command features only."""
    features: set[str] = set()
    sources: list[SourceCommand] = []

    for item in commands:
        if isinstance(item, dict):
            command_id = str(item.get("command_id") or "")
            feature = item.get("feature") or None
            name = str(item.get("name") or command_id)
        else:
            command_id = str(item[0])
            feature = item[1] or None
            name = str(item[2] or command_id)
        if feature not in COMMAND_FEATURE_SET:
            continue
        features.add(feature)
        if feature == "source":
            sources.append(SourceCommand(command_id=command_id, name=name))

    feature_set = frozenset(features)
    power_mode = _infer_power_mode(feature_set)
    media_features = _infer_media_features(feature_set)
    sorted_sources = tuple(sorted(sources, key=lambda source: source.name.lower()))
    source_names = {source.command_id: source.name for source in sorted_sources}
    source_commands = tuple(source.command_id for source in sorted_sources)
    is_pure_switch = bool(feature_set & POWER_FEATURES) and feature_set <= POWER_FEATURES
    return DeviceCapabilities(
        features=feature_set,
        power_mode=power_mode,
        media_features=media_features,
        source_commands=source_commands,
        source_names=source_names,
        sources=sorted_sources,
        is_pure_switch=is_pure_switch,
    )


def _infer_power_mode(features: frozenset[str]) -> str:
    if {"power_on", "power_off"} <= features:
        return "explicit"
    if "power_toggle" in features:
        return "toggle"
    return "none"


def _infer_media_features(features: frozenset[str]) -> frozenset[str]:
    media_features: set[str] = set()
    if "play" in features:
        media_features.add("play")
    if "pause" in features or "play_pause_toggle" in features:
        media_features.add("pause")
    if "stop" in features:
        media_features.add("stop")
    if "next" in features:
        media_features.add("next")
    if "previous" in features:
        media_features.add("previous")
    if {"volume_up", "volume_down"} <= features:
        media_features.add("volume_step")
    if {"mute", "unmute"} <= features or "mute_toggle" in features:
        media_features.add("mute")
    if "source" in features:
        media_features.add("source")
    return frozenset(media_features)
