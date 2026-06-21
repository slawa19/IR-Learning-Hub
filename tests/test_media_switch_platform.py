"""Pytest tests for media_player and switch consumer platforms."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from unittest.mock import AsyncMock

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from homeassistant.components.media_player.const import MediaPlayerEntityFeature
from homeassistant.const import STATE_IDLE, STATE_OFF, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import State
from homeassistant.exceptions import ServiceValidationError

from custom_components.ir_learning_hub.const import DOMAIN
from custom_components.ir_learning_hub.media_player import (
    IRLearningHubMediaPlayerEntity,
    MediaPlayerEntityManager,
    media_player_features,
    source_command_for_name,
)
from custom_components.ir_learning_hub.registry_runtime import EntitySpec, desired_entities
from custom_components.ir_learning_hub.remote import RemoteEntityManager
from custom_components.ir_learning_hub.switch import (
    IRLearningHubSwitchEntity,
    SwitchEntityManager,
)


class FakeStore:
    def __init__(self, data=None) -> None:
        self.transmitter = {"ieee": "00:11", "config": {}}
        self.data = data or {"transmitters": {"0011": self.transmitter}}

    def resolve_transmitter(self, transmitter_id=None):
        return self.transmitter

    def get_command(self, location_id, ir_device_id, command_id):
        return {"code": f"code-{command_id}", "format": "zosung_base64"}


class FakeHass:
    def async_create_task(self, coro):
        coro.close()
        return type(
            "Task",
            (),
            {"done": lambda self: True, "cancel": lambda self: None},
        )()


def spec_from_commands(commands, *, preferred_domain="media_player", device_type="media_player"):
    command_map = {
        command_id: {
            "feature": "source" if command_id.startswith("source_") else command_id,
            "name": command_id.removeprefix("source_").replace("_", " ").upper()
            if command_id.startswith("source_")
            else command_id,
        }
        for command_id in commands
    }
    [spec] = desired_entities(
        {
            "locations": {
                "living": {
                    "devices": {
                        "amp": {
                            "name": "Amp",
                            "type": device_type,
                            "preferred_domain": preferred_domain,
                            "commands": command_map,
                        }
                    }
                }
            }
        }
    )
    return spec


def no_state_write(entity) -> None:
    entity.async_write_ha_state = lambda: None


@pytest.mark.parametrize(
    ("commands", "expected"),
    [
        ({"play"}, MediaPlayerEntityFeature.PLAY),
        ({"pause"}, MediaPlayerEntityFeature.PAUSE),
        ({"stop"}, MediaPlayerEntityFeature.STOP),
        ({"next"}, MediaPlayerEntityFeature.NEXT_TRACK),
        ({"previous"}, MediaPlayerEntityFeature.PREVIOUS_TRACK),
        ({"volume_up", "volume_down"}, MediaPlayerEntityFeature.VOLUME_STEP),
        ({"mute_toggle"}, MediaPlayerEntityFeature.VOLUME_MUTE),
        ({"source_cd"}, MediaPlayerEntityFeature.SELECT_SOURCE),
        (
            {"power_on", "power_off"},
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF,
        ),
        (
            {"power_toggle"},
            MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF,
        ),
    ],
)
def test_media_player_feature_mapping(commands, expected) -> None:
    spec = spec_from_commands(commands)

    assert media_player_features(spec) & expected == expected


def test_media_player_no_power_mode_does_not_advertise_turn_on_off() -> None:
    spec = spec_from_commands({"play"})

    assert not media_player_features(spec) & MediaPlayerEntityFeature.TURN_ON
    assert not media_player_features(spec) & MediaPlayerEntityFeature.TURN_OFF


def test_source_reverse_mapping_uses_display_name() -> None:
    [spec] = desired_entities(
        {
            "locations": {
                "living": {
                    "devices": {
                        "amp": {
                            "name": "Amp",
                            "type": "media_player",
                            "preferred_domain": "media_player",
                            "commands": {
                                "cd": {"feature": "source", "name": "CD"},
                                "video_1": {"feature": "source", "name": "Video 1"},
                            },
                        }
                    }
                }
            }
        }
    )

    assert spec.capabilities.source_names == {
        "cd": "CD",
        "video_1": "Video 1",
    }
    assert source_command_for_name(spec, "Video 1") == "video_1"
    with pytest.raises(ServiceValidationError, match="has no source Tape"):
        source_command_for_name(spec, "Tape")


def test_switch_domain_selection_requires_pure_switch() -> None:
    pure = spec_from_commands(
        {"power_on", "power_off"},
        preferred_domain="auto",
        device_type="switch",
    )
    mixed = spec_from_commands(
        {"power_toggle", "play"},
        preferred_domain="switch",
        device_type="generic",
    )

    assert pure.domain == "switch"
    assert pure.unique_id == "living__amp__switch"
    assert mixed.domain == "remote"


def test_media_player_methods_send_expected_command_ids() -> None:
    spec = spec_from_commands(
        {
            "power_on",
            "power_off",
            "play",
            "pause",
            "stop",
            "next",
            "previous",
            "volume_up",
            "volume_down",
            "mute",
            "unmute",
            "source_cd",
        }
    )
    entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec)
    no_state_write(entity)
    send = AsyncMock()
    entity.async_send_feature_command = send
    raw_send = AsyncMock()
    entity.async_send_stored_command = raw_send

    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_media_play())
    asyncio.run(entity.async_media_pause())
    asyncio.run(entity.async_media_stop())
    asyncio.run(entity.async_media_next_track())
    asyncio.run(entity.async_media_previous_track())
    asyncio.run(entity.async_volume_up())
    asyncio.run(entity.async_volume_down())
    asyncio.run(entity.async_mute_volume(True))
    asyncio.run(entity.async_mute_volume(False))
    asyncio.run(entity.async_select_source("CD"))
    asyncio.run(entity.async_turn_off())

    assert [call.args[0] for call in send.await_args_list] == [
        "power_on",
        "play",
        "pause",
        "stop",
        "next",
        "previous",
        "volume_up",
        "volume_down",
        "mute",
        "unmute",
        "power_off",
    ]
    raw_send.assert_awaited_once_with("source_cd")
    assert entity.state == STATE_OFF
    assert entity.source == "CD"
    assert entity.is_volume_muted is False


def test_media_player_mute_only_device_treats_mute_as_toggle_for_both_calls() -> None:
    spec = spec_from_commands({"mute"})
    entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec)
    no_state_write(entity)
    send = AsyncMock()
    entity.async_send_feature_command = send

    asyncio.run(entity.async_mute_volume(True))
    asyncio.run(entity.async_mute_volume(False))

    assert [call.args[0] for call in send.await_args_list] == ["mute", "mute"]
    assert entity.is_volume_muted is False


def test_media_player_update_spec_writes_new_features_and_sources_immediately() -> None:
    entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec_from_commands({"play"}))
    snapshots = []

    def capture_state_write() -> None:
        snapshots.append(
            (
                entity.supported_features,
                entity.source_list,
            )
        )

    entity.async_write_ha_state = capture_state_write
    entity.entity_id = "media_player.amp"

    entity.update_spec(spec_from_commands({"play", "source_cd"}))

    assert snapshots == [
        (
            MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.SELECT_SOURCE,
            ["CD"],
        )
    ]


def test_media_player_pause_falls_back_to_play_pause_toggle() -> None:
    spec = spec_from_commands({"play_pause_toggle"})
    entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec)
    no_state_write(entity)
    send = AsyncMock()
    entity.async_send_feature_command = send

    asyncio.run(entity.async_media_pause())

    send.assert_awaited_once_with("play_pause_toggle")
    assert entity.state == STATE_PAUSED


def test_media_player_power_modes_are_honest() -> None:
    none_entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec_from_commands({"play"}))
    no_state_write(none_entity)
    with pytest.raises(ServiceValidationError, match="no supported power command"):
        asyncio.run(none_entity.async_turn_off())

    toggle_entity = IRLearningHubMediaPlayerEntity(
        FakeStore(),
        spec_from_commands({"power_toggle"}),
    )
    no_state_write(toggle_entity)
    send = AsyncMock()
    toggle_entity.async_send_feature_command = send

    asyncio.run(toggle_entity.async_turn_on())
    asyncio.run(toggle_entity.async_turn_off())

    assert [call.args[0] for call in send.await_args_list] == [
        "power_toggle",
        "power_toggle",
    ]
    assert toggle_entity.assumed_state is True
    assert toggle_entity.state == STATE_OFF


def test_media_player_restore_state_including_source_and_mute() -> None:
    entity = IRLearningHubMediaPlayerEntity(FakeStore(), spec_from_commands({"play"}))
    entity.async_get_last_state = AsyncMock(
        return_value=State(
            "media_player.amp",
            STATE_PLAYING,
            {"source": "CD", "is_volume_muted": True},
        )
    )

    asyncio.run(entity.async_added_to_hass())

    assert entity.state == STATE_PLAYING
    assert entity.source == "CD"
    assert entity.is_volume_muted is True


def test_switch_methods_are_optimistic_and_assumed() -> None:
    spec = spec_from_commands(
        {"power_toggle"},
        preferred_domain="auto",
        device_type="switch",
    )
    entity = IRLearningHubSwitchEntity(FakeStore(), spec)
    no_state_write(entity)
    send = AsyncMock()
    entity.async_send_feature_command = send

    asyncio.run(entity.async_turn_on())
    asyncio.run(entity.async_toggle())
    asyncio.run(entity.async_turn_off())

    assert [call.args[0] for call in send.await_args_list] == [
        "power_toggle",
        "power_toggle",
        "power_toggle",
    ]
    assert entity.assumed_state is True
    assert entity.is_on is False


def test_media_and_switch_managers_remove_registry_entries(monkeypatch) -> None:
    for manager_class, preferred_domain, device_type, unique_id in (
        (MediaPlayerEntityManager, "media_player", "media_player", "living__amp"),
        (SwitchEntityManager, "auto", "switch", "living__amp__switch"),
    ):
        store = FakeStore(
            {
                "transmitters": {"0011": {"ieee": "00:11", "config": {}}},
                "locations": {
                    "living": {
                        "devices": {
                            "amp": {
                                "name": "Amp",
                                "type": device_type,
                                "preferred_domain": preferred_domain,
                                "commands": {
                                    "on": {"feature": "power_on"},
                                    "off": {"feature": "power_off"},
                                },
                            }
                        }
                    }
                },
            }
        )
        added = []
        manager = manager_class(FakeHass(), store, lambda entities: added.extend(entities))
        asyncio.run(manager.async_reconcile())
        entity = manager.entities[unique_id]
        entity.entity_id = f"{entity._spec.domain}.amp"
        entity.async_remove = AsyncMock()
        removed_entity_ids = []
        removed_device_ids = []

        class FakeEntityRegistry:
            def __init__(self) -> None:
                self.entities = {
                    entity.entity_id: type(
                        "EntityEntry",
                        (),
                        {"device_id": "device-1"},
                    )()
                }

            def async_get(self, entity_id):
                return self.entities.get(entity_id)

            def async_remove(self, entity_id):
                removed_entity_ids.append(entity_id)
                self.entities.pop(entity_id, None)

        class FakeDeviceRegistry:
            def async_get_device(self, identifiers):
                if identifiers == {(DOMAIN, "living__amp")}:
                    return type("DeviceEntry", (), {"id": "device-1"})()
                return None

            def async_remove_device(self, device_id):
                removed_device_ids.append(device_id)

        fake_entity_registry = FakeEntityRegistry()
        monkeypatch.setattr(
            "custom_components.ir_learning_hub.consumer.er.async_get",
            lambda hass: fake_entity_registry,
        )
        monkeypatch.setattr(
            "custom_components.ir_learning_hub.consumer.dr.async_get",
            lambda hass: FakeDeviceRegistry(),
        )
        store.data["locations"]["living"]["devices"] = {}

        asyncio.run(manager.async_reconcile())

        entity.async_remove.assert_awaited_once()
        assert removed_entity_ids == [entity.entity_id]
        assert removed_device_ids == ["device-1"]


def test_cross_domain_transition_remote_to_media_player(monkeypatch) -> None:
    store = FakeStore(
        {
            "transmitters": {"0011": {"ieee": "00:11", "config": {}}},
            "locations": {
                "living": {
                    "devices": {
                        "amp": {
                            "name": "Amp",
                            "type": "generic",
                            "preferred_domain": "remote",
                            "commands": {"play_button": {"feature": "play"}},
                        }
                    }
                }
            },
        }
    )
    remote_added = []
    media_added = []
    remote_manager = RemoteEntityManager(FakeHass(), store, lambda entities: remote_added.extend(entities))
    media_manager = MediaPlayerEntityManager(FakeHass(), store, lambda entities: media_added.extend(entities))
    asyncio.run(remote_manager.async_reconcile())
    asyncio.run(media_manager.async_reconcile())
    remote_entity = remote_manager.entities["living__amp"]
    remote_entity.entity_id = "remote.amp"
    remote_entity.async_remove = AsyncMock()
    removed_entity_ids = []

    class FakeEntityRegistry:
        def __init__(self) -> None:
            self.entities = {
                "remote.amp": type("EntityEntry", (), {"device_id": "device-1"})()
            }

        def async_get(self, entity_id):
            return self.entities.get(entity_id)

        def async_remove(self, entity_id):
            removed_entity_ids.append(entity_id)
            self.entities.pop(entity_id, None)

    class FakeDeviceRegistry:
        def async_get_device(self, identifiers):
            return type("DeviceEntry", (), {"id": "device-1"})()

        def async_remove_device(self, device_id):
            pass

    fake_entity_registry = FakeEntityRegistry()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.consumer.er.async_get",
        lambda hass: fake_entity_registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.consumer.dr.async_get",
        lambda hass: FakeDeviceRegistry(),
    )

    store.data["locations"]["living"]["devices"]["amp"]["preferred_domain"] = "media_player"
    asyncio.run(remote_manager.async_reconcile())
    asyncio.run(media_manager.async_reconcile())

    remote_entity.async_remove.assert_awaited_once()
    assert removed_entity_ids == ["remote.amp"]
    assert remote_manager.entities == {}
    assert set(media_manager.entities) == {"living__amp"}
    assert len(media_added) == 1
