"""Pure command capability inference for IR Learning Hub."""

from __future__ import annotations

from dataclasses import dataclass


COMMAND_ALIASES: dict[str, str] = {
    "vol_up": "volume_up",
    "vol_down": "volume_down",
    "power": "power_toggle",
    "forward": "fast_forward",
    "backward": "rewind",
    "ok": "select",
    "return": "back",
    "input_tv": "source_tv",
    "input_pc": "source_pc",
}

POWER_COMMANDS = frozenset({"power_on", "power_off", "power_toggle"})
PLAYBACK_COMMANDS = frozenset(
    {
        "play",
        "pause",
        "play_pause_toggle",
        "stop",
        "next",
        "previous",
        "fast_forward",
        "rewind",
        "eject",
    }
)
VOLUME_COMMANDS = frozenset({"volume_up", "volume_down", "mute", "unmute", "mute_toggle"})
SOURCE_ACRONYMS = frozenset({"aux", "bd", "cd", "dvd", "hdmi", "pc", "tv", "usb"})


@dataclass(frozen=True)
class DeviceCapabilities:
    """Inferred features for one registry device."""

    commands: frozenset[str]
    power_mode: str
    media_features: frozenset[str]
    source_commands: tuple[str, ...]
    source_names: dict[str, str]
    is_pure_switch: bool

    @property
    def assumed_power(self) -> bool:
        """Return true when power state cannot be known from explicit on/off commands."""
        return self.power_mode == "toggle"


def normalize_command_id(command_id: str) -> str:
    """Normalize a stored command id to the canonical vocabulary."""
    return COMMAND_ALIASES.get(command_id, command_id)


def normalize_command_ids(command_ids: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> frozenset[str]:
    """Normalize a collection of command ids."""
    return frozenset(normalize_command_id(command_id) for command_id in command_ids)


def source_display_name(command_id: str) -> str:
    """Format a canonical source_* command id for UI source lists."""
    if not command_id.startswith("source_"):
        return command_id.replace("_", " ").title()
    source = command_id.removeprefix("source_")
    parts = source.split("_")
    return " ".join(
        part.upper() if part in SOURCE_ACRONYMS else part.title()
        for part in parts
    )


def infer_capabilities(command_ids: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> DeviceCapabilities:
    """Infer device capabilities from command ids only."""
    commands = normalize_command_ids(command_ids)
    power_mode = _infer_power_mode(commands)
    media_features = _infer_media_features(commands)
    source_commands = tuple(sorted(command for command in commands if command.startswith("source_")))
    source_names = {
        command: source_display_name(command)
        for command in source_commands
    }
    is_pure_switch = bool(commands & POWER_COMMANDS) and commands <= POWER_COMMANDS
    return DeviceCapabilities(
        commands=commands,
        power_mode=power_mode,
        media_features=media_features,
        source_commands=source_commands,
        source_names=source_names,
        is_pure_switch=is_pure_switch,
    )


def _infer_power_mode(commands: frozenset[str]) -> str:
    if {"power_on", "power_off"} <= commands:
        return "explicit"
    if "power_toggle" in commands:
        return "toggle"
    return "none"


def _infer_media_features(commands: frozenset[str]) -> frozenset[str]:
    features: set[str] = set()
    if "play" in commands:
        features.add("play")
    if "pause" in commands or "play_pause_toggle" in commands:
        features.add("pause")
    if "stop" in commands:
        features.add("stop")
    if "next" in commands:
        features.add("next")
    if "previous" in commands:
        features.add("previous")
    if {"volume_up", "volume_down"} <= commands:
        features.add("volume_step")
    if "mute" in commands or "mute_toggle" in commands:
        features.add("mute")
    if any(command.startswith("source_") for command in commands):
        features.add("source")
    return frozenset(features)
