"""Pytest tests for HA-backed remote and emitter pieces."""

from __future__ import annotations

import importlib.util
import asyncio
from unittest.mock import AsyncMock
import unittest

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from custom_components.ir_learning_hub.const import CONF_IEEE, DOMAIN
from custom_components.ir_learning_hub import (
    CONSUMER_PLATFORMS,
    _entry_platforms,
    _remove_entry_and_select_new_owner,
)
from custom_components.ir_learning_hub.infrared import IRLearningHubInfraredEmitter
from custom_components.ir_learning_hub.ir_command import ZosungCommand
from custom_components.ir_learning_hub.registry_runtime import EntitySpec, desired_entities
from custom_components.ir_learning_hub.remote import RemoteEntityManager, async_send_registry_command


class FakeStore:
    def __init__(self) -> None:
        self.transmitter = {"ieee": "00:11", "config": {}}
        self.data = {"transmitters": {"0011": self.transmitter}}

    def resolve_transmitter(self, transmitter_id=None):
        if transmitter_id == "stale":
            raise ValueError("stale transmitter")
        return self.transmitter

    def get_command(self, location_id, ir_device_id, command_id):
        return {"code": f"code-{command_id}", "format": "zosung_base64"}


def test_emitter_forwards_zosung_command_to_adapter() -> None:
    store = FakeStore()
    adapter = type("Adapter", (), {"async_send": AsyncMock()})()
    emitter = IRLearningHubInfraredEmitter(
        store,
        adapter,
        "0011",
        {CONF_IEEE: "00:11"},
    )

    asyncio.run(emitter.async_send_command(ZosungCommand("abc")))

    adapter.async_send.assert_awaited_once_with(store.transmitter, "abc")


def test_consumer_send_uses_infrared_entity_registry_and_helper(monkeypatch) -> None:
    send_mock = AsyncMock()
    fake_registry = type(
        "Registry",
        (),
        {
            "async_get_entity_id": lambda self, domain, platform, unique_id: (
                "infrared.ir_transmitter"
                if (domain, platform, unique_id) == ("infrared", DOMAIN, "0011")
                else None
            )
        },
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.remote.er.async_get",
        lambda hass: fake_registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.remote.infrared.async_send_command",
        send_mock,
    )
    store = FakeStore()
    [spec] = desired_entities(
        {
            "locations": {
                "living": {
                    "devices": {
                        "tv": {
                            "name": "TV",
                            "type": "generic",
                            "preferred_domain": "remote",
                            "transmitter_id": "stale",
                            "commands": {"power": {}},
                        }
                    }
                }
            }
        }
    )

    asyncio.run(async_send_registry_command(object(), store, spec, "power_toggle"))

    send_mock.assert_awaited_once()
    _, emitter_entity_id, command = send_mock.await_args.args[:3]
    assert emitter_entity_id == "infrared.ir_transmitter"
    assert command.code == "code-power"
    assert send_mock.await_args.kwargs.get("context") is None


def test_consumer_send_raises_for_missing_command() -> None:
    spec = EntitySpec(
        domain="remote",
        unique_id="living__tv",
        location_id="living",
        ir_device_id="tv",
        name="TV",
        transmitter_id=None,
        command_ids=(),
        command_keys={},
        capabilities=desired_entities(
            {
                "locations": {
                    "living": {
                        "devices": {
                            "tv": {
                                "name": "TV",
                                "type": "generic",
                                "commands": {},
                            }
                        }
                    }
                }
            }
        )[0].capabilities,
    )

    with pytest.raises(Exception, match="has no command_id play"):
        asyncio.run(async_send_registry_command(object(), FakeStore(), spec, "play"))


def test_consumer_owner_platforms_and_re_election() -> None:
    owner = object()
    secondary = object()
    domain_data = {
        "consumer_owner": "owner",
        "entries": {"owner": owner, "secondary": secondary},
    }

    assert CONSUMER_PLATFORMS[0] in _entry_platforms(domain_data, "owner")
    assert CONSUMER_PLATFORMS[0] not in _entry_platforms(domain_data, "secondary")

    new_owner = _remove_entry_and_select_new_owner(domain_data, "owner")

    assert new_owner == "secondary"
    assert domain_data["consumer_owner"] == "secondary"


def test_remote_manager_reconcile_is_idempotent_and_removes_missing_entities(monkeypatch) -> None:
    store = FakeStore()
    store.data["locations"] = {
        "living": {
            "devices": {
                "tv": {
                    "name": "TV",
                    "type": "generic",
                    "preferred_domain": "remote",
                    "commands": {"power_toggle": {}},
                }
            }
        }
    }
    added = []
    manager = RemoteEntityManager(
        type("Hass", (), {"async_create_task": lambda self, coro: None})(),
        store,
        lambda entities: added.extend(entities),
    )

    asyncio.run(manager.async_reconcile())
    asyncio.run(manager.async_reconcile())

    assert len(added) == 1
    assert set(manager.entities) == {"living__tv"}
    assert added[0].device_info["via_device"] == (DOMAIN, "0011")

    remove_mock = AsyncMock()
    manager.entities["living__tv"].async_remove = remove_mock
    store.data["locations"]["living"]["devices"] = {}

    asyncio.run(manager.async_reconcile())

    remove_mock.assert_awaited_once()
    assert manager.entities == {}


def test_remote_manager_coalesces_and_cancels_scheduled_reconcile() -> None:
    created = []

    class Task:
        def __init__(self) -> None:
            self.cancelled = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancelled = True

    class Hass:
        def async_create_task(self, coro):
            coro.close()
            task = Task()
            created.append(task)
            return task

    manager = RemoteEntityManager(Hass(), FakeStore(), lambda entities: None)

    manager.async_schedule_reconcile()
    manager.async_schedule_reconcile()

    assert len(created) == 1

    manager.async_unload()

    assert created[0].cancelled
    assert manager._reconcile_task is None
