"""Media player consumer entities for IR Learning Hub."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_OFF, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .consumer import (
    ConsumerEntityManager,
    RegistryBackedConsumerEntity,
    async_setup_consumer_platform,
)
from .registry_runtime import EntitySpec
from .storage import IRRegistryStore

MEDIA_PLAYER_DOMAIN = "media_player"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up registry-backed media player entities for the owner entry."""
    await async_setup_consumer_platform(
        hass,
        entry,
        async_add_entities,
        manager_key="media_player_manager",
        platform_domain=MEDIA_PLAYER_DOMAIN,
        entity_factory=IRLearningHubMediaPlayerEntity,
    )


def media_player_features(spec: EntitySpec) -> MediaPlayerEntityFeature:
    """Return supported media player features for an entity spec."""
    capabilities = spec.capabilities
    features = MediaPlayerEntityFeature(0)
    if "play" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.PLAY
    if "pause" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.PAUSE
    if "stop" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.STOP
    if "next" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.NEXT_TRACK
    if "previous" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
    if "volume_step" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.VOLUME_STEP
    if "mute" in capabilities.media_features:
        features |= MediaPlayerEntityFeature.VOLUME_MUTE
    if capabilities.source_commands:
        features |= MediaPlayerEntityFeature.SELECT_SOURCE
    if capabilities.power_mode in {"explicit", "toggle"}:
        features |= MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
    return features


def source_command_for_name(spec: EntitySpec, source: str) -> str:
    """Return the source_* command id for a human-readable source name."""
    source_commands = {
        name: command_id
        for command_id, name in spec.capabilities.source_names.items()
    }
    command_id = source_commands.get(source)
    if command_id is None:
        raise ServiceValidationError(
            f"IR device {spec.device_identifier} has no source {source}"
        )
    return command_id


class IRLearningHubMediaPlayerEntity(
    RegistryBackedConsumerEntity,
    MediaPlayerEntity,
    RestoreEntity,
):
    """Media player entity backed by stored IR commands."""

    def __init__(
        self,
        store: IRRegistryStore,
        spec: EntitySpec,
    ) -> None:
        """Initialize the media player."""
        self._attr_state = STATE_IDLE
        self._attr_source = None
        self._attr_is_volume_muted = None
        super().__init__(store, spec)

    def update_spec(self, spec: EntitySpec) -> None:
        """Update media-player metadata from a new desired spec."""
        super().update_spec(spec)
        self._attr_supported_features = media_player_features(spec)
        self._attr_source_list = [
            spec.capabilities.source_names[command_id]
            for command_id in spec.capabilities.source_commands
        ] or None
        if spec.capabilities.power_mode == "none" and self._attr_state == STATE_OFF:
            self._attr_state = STATE_IDLE

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed media state and source."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is None:
            return
        if state.state != STATE_OFF or self._spec.capabilities.power_mode != "none":
            self._attr_state = state.state
        self._attr_source = state.attributes.get("source")
        if "is_volume_muted" in state.attributes:
            self._attr_is_volume_muted = state.attributes["is_volume_muted"]

    async def async_turn_on(self) -> None:
        """Turn the media device on."""
        await self._send_power("power_on")
        self._attr_state = STATE_IDLE
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn the media device off."""
        await self._send_power("power_off")
        self._attr_state = STATE_OFF
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Send play command."""
        await self.async_send_stored_command("play")
        self._attr_state = STATE_PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self.async_send_stored_command(_first_supported(self._spec, "pause", "play_pause_toggle"))
        self._attr_state = STATE_PAUSED
        self.async_write_ha_state()

    async def async_media_play_pause(self) -> None:
        """Send play/pause toggle command."""
        await self.async_send_stored_command(
            _first_supported(self._spec, "play_pause_toggle", "pause", "play")
        )
        self._attr_state = (
            STATE_PAUSED if self._attr_state == STATE_PLAYING else STATE_PLAYING
        )
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command."""
        await self.async_send_stored_command("stop")
        self._attr_state = STATE_IDLE
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next-track command."""
        await self.async_send_stored_command("next")

    async def async_media_previous_track(self) -> None:
        """Send previous-track command."""
        await self.async_send_stored_command("previous")

    async def async_volume_up(self) -> None:
        """Send volume-up command."""
        await self.async_send_stored_command("volume_up")

    async def async_volume_down(self) -> None:
        """Send volume-down command."""
        await self.async_send_stored_command("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Send mute or unmute command."""
        if mute:
            command_id = _first_supported(self._spec, "mute", "mute_toggle")
        else:
            command_id = _first_supported(self._spec, "unmute", "mute_toggle")
        await self.async_send_stored_command(command_id)
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        """Select an input source."""
        command_id = source_command_for_name(self._spec, source)
        await self.async_send_stored_command(command_id)
        self._attr_source = source
        self.async_write_ha_state()

    async def _send_power(self, explicit_command_id: str) -> None:
        power_mode = self._spec.capabilities.power_mode
        if power_mode == "explicit":
            await self.async_send_stored_command(explicit_command_id)
            return
        if power_mode == "toggle":
            await self.async_send_stored_command("power_toggle")
            return
        raise ServiceValidationError(
            f"IR device {self._spec.device_identifier} has no supported power command"
        )


class MediaPlayerEntityManager(ConsumerEntityManager):
    """Runtime materializer for media player entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: IRRegistryStore,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Initialize the media player manager."""
        super().__init__(
            hass,
            store,
            async_add_entities,
            MEDIA_PLAYER_DOMAIN,
            IRLearningHubMediaPlayerEntity,
        )


def _first_supported(spec: EntitySpec, *command_ids: str) -> str:
    for command_id in command_ids:
        if command_id in spec.command_keys:
            return command_id
    raise ServiceValidationError(
        f"IR device {spec.device_identifier} has no supported command among {command_ids}"
    )
