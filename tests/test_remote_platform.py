"""Pytest tests for HA-backed remote and emitter pieces."""

from __future__ import annotations

import importlib.util
import asyncio
from unittest.mock import AsyncMock
import unittest

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.ir_learning_hub.const import CONF_IEEE, DOMAIN
from custom_components.ir_learning_hub.errors import IRLearningHubError
from custom_components.ir_learning_hub import (
    CONSUMER_PLATFORMS,
    ENTRY_PLATFORMS,
    REGISTERED_SERVICES,
    _register_services,
    resolve_transmitter_ref,
    async_setup_entry,
    async_remove_entry,
    async_unload_entry,
    _entry_platforms,
    _register_transmitter_device,
    _remove_entry_and_select_new_owner,
)
from custom_components.ir_learning_hub.infrared import (
    IRLearningHubInfraredEmitter,
    _transmitter_device_info,
)
from custom_components.ir_learning_hub.ir_command import ZosungCommand
from custom_components.ir_learning_hub.registry_runtime import EntitySpec, desired_entities
from custom_components.ir_learning_hub.remote import (
    IRLearningHubRemoteEntity,
    RemoteEntityManager,
    async_send_registry_command,
)
from custom_components.ir_learning_hub.storage import IRRegistryStore


class FakeStore:
    def __init__(self) -> None:
        self.transmitter = {"ieee": "00:11", "config": {}}
        self.data = {"transmitters": {"0011": self.transmitter}}

    def resolve_transmitter(self, transmitter_id=None):
        if transmitter_id == "stale":
            raise IRLearningHubError("transmitter_unavailable", "Transmitter stale is not available")
        return self.transmitter

    def get_command(self, location_id, ir_device_id, command_id):
        return {"code": f"code-{command_id}", "format": "zosung_base64"}


class FakeEntry:
    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id


class FakeConfigEntries:
    def __init__(self) -> None:
        self.forwarded = []
        self.unloaded = []
        self.reloads = []
        self._entries = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, list(platforms)))
        return True

    def async_schedule_reload(self, entry_id):
        self.reloads.append(entry_id)

    def async_entries(self, domain=None):
        return list(self._entries)


class FakeServices:
    def __init__(self) -> None:
        self.removed = []
        self.registered = {}

    def async_remove(self, domain, service):
        self.removed.append((domain, service))

    def async_register(
        self,
        domain,
        service,
        callback,
        schema=None,
        supports_response=None,
    ):
        self.registered[(domain, service)] = callback


class FakeHass:
    def __init__(self, domain_data=None) -> None:
        self.data = {}
        if domain_data is not None:
            self.data[DOMAIN] = domain_data
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices()


class FakeSetupStore:
    async def async_load(self):
        return None

    async def async_upsert_transmitter_from_entry(self, entry_data):
        return "0011"

    async def async_reconcile_transmitters(self, valid_keys):
        self.valid_keys = valid_keys


class FakeRemovalStore:
    def __init__(self) -> None:
        self.data = {"transmitters": {"0011": {"ieee": "00:11"}}}
        self.saved = False

    async def async_save(self) -> None:
        self.saved = True


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


def test_emitter_device_info_attaches_to_registered_transmitter_device() -> None:
    device_info = _transmitter_device_info("0011", {CONF_IEEE: "00:11"})

    assert device_info == {"identifiers": {(DOMAIN, "0011")}}


def test_transmitter_device_registration_owns_ts1201_metadata(monkeypatch) -> None:
    calls = []
    registry = type(
        "DeviceRegistry",
        (),
        {"async_get_or_create": lambda self, **kwargs: calls.append(kwargs)},
    )()
    entry = type(
        "Entry",
        (),
        {"entry_id": "entry-1", "data": {CONF_IEEE: "AA:BB:CC"}},
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_get",
        lambda hass: registry,
    )

    _register_transmitter_device(object(), entry, "aa_bb_cc")

    assert calls == [
        {
            "config_entry_id": "entry-1",
            "identifiers": {(DOMAIN, "aa_bb_cc")},
            "via_device": ("zha", "aa:bb:cc"),
            "name": "IR transmitter aa:bb:cc",
            "manufacturer": "Tuya",
            "model": "TS1201 / MOES UFO-R11",
        }
    ]


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
        "custom_components.ir_learning_hub.consumer.er.async_get",
        lambda hass: fake_registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.consumer.infrared.async_send_command",
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
                            "commands": {"power": {"feature": "power_toggle"}},
                        }
                    }
                }
            }
        }
    )

    with pytest.raises(ServiceValidationError, match="Transmitter stale is not available"):
        asyncio.run(async_send_registry_command(object(), store, spec, "power"))


def test_consumer_send_uses_explicit_transmitter_without_fallback(monkeypatch) -> None:
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
        "custom_components.ir_learning_hub.consumer.er.async_get",
        lambda hass: fake_registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.consumer.infrared.async_send_command",
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
                            "transmitter_id": "0011",
                            "commands": {"power": {"feature": "power_toggle"}},
                        }
                    }
                }
            }
        }
    )

    asyncio.run(async_send_registry_command(object(), store, spec, "power"))

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
        feature_keys={},
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

    with pytest.raises(ServiceValidationError, match="has no command_id play"):
        asyncio.run(async_send_registry_command(object(), FakeStore(), spec, "play"))


def test_remote_power_command_raises_service_validation_error() -> None:
    spec = desired_entities(
        {
            "locations": {
                "living": {
                    "devices": {
                        "tv": {
                            "name": "TV",
                            "type": "generic",
                            "preferred_domain": "remote",
                            "commands": {"play": {"feature": "play"}},
                        }
                    }
                }
            }
        }
    )[0]
    entity = IRLearningHubRemoteEntity(FakeStore(), spec)

    with pytest.raises(ServiceValidationError, match="no supported power command"):
        asyncio.run(entity.async_turn_on())


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


def test_setup_entry_tracks_forwarded_platforms_after_forward(monkeypatch) -> None:
    hass = FakeHass()
    entry = type(
        "Entry",
        (),
        {"entry_id": "owner", "data": {CONF_IEEE: "00:11"}},
    )()
    hass.config_entries._entries = [entry]
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.IRRegistryStore",
        lambda hass: FakeSetupStore(),
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.ZHAAdapter",
        lambda hass: object(),
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub._async_register_frontend",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub._register_services",
        lambda hass: None,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub._register_transmitter_device",
        lambda hass, entry, transmitter_id: None,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True

    domain_data = hass.data[DOMAIN]
    expected_platforms = ENTRY_PLATFORMS + CONSUMER_PLATFORMS
    assert hass.config_entries.forwarded == [("owner", expected_platforms)]
    assert domain_data["entries"] == {"owner": entry}
    assert domain_data["consumer_owner"] == "owner"
    assert domain_data["forwarded"] == {"owner": expected_platforms}
    assert domain_data["store"].valid_keys == {"0011"}


def test_resolve_transmitter_ref_accepts_key_ieee_and_entity_id(monkeypatch) -> None:
    store = FakeStore()
    registry = type(
        "Registry",
        (),
        {
            "async_get": lambda self, entity_id: type(
                "EntityEntry",
                (),
                {
                    "domain": "infrared",
                    "platform": DOMAIN,
                    "unique_id": "0011",
                },
            )()
            if entity_id == "infrared.ir_transmitter_00_11"
            else None
        },
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.er.async_get",
        lambda hass: registry,
    )

    hass = object()
    assert resolve_transmitter_ref(hass, store, "0011") == "0011"
    assert resolve_transmitter_ref(hass, store, "00:11") == "0011"
    assert resolve_transmitter_ref(hass, store, "infrared.ir_transmitter_00_11") == "0011"


def test_resolve_transmitter_ref_rejects_unknown(monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.er.async_get",
        lambda hass: type("Registry", (), {"async_get": lambda self, entity_id: None})(),
    )

    with pytest.raises(ServiceValidationError, match="Unknown IR transmitter: nope"):
        resolve_transmitter_ref(object(), FakeStore(), "nope")


def test_remove_owner_re_elects_once_and_schedules_reload() -> None:
    domain_data = {
        "consumer_owner": "owner",
        "entries": {
            "owner": FakeEntry("owner"),
            "secondary": FakeEntry("secondary"),
            "third": FakeEntry("third"),
        },
        "forwarded": {
            "owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS,
            "secondary": ENTRY_PLATFORMS,
            "third": ENTRY_PLATFORMS,
        },
        "learn_tasks": {},
    }
    hass = FakeHass(domain_data)

    asyncio.run(async_remove_entry(hass, FakeEntry("owner")))

    assert domain_data["consumer_owner"] == "secondary"
    assert set(domain_data["entries"]) == {"secondary", "third"}
    assert set(domain_data["forwarded"]) == {"secondary", "third"}
    assert hass.config_entries.reloads == ["secondary"]
    assert DOMAIN in hass.data


def test_remove_entry_deletes_transmitter_from_store() -> None:
    store = FakeRemovalStore()
    domain_data = {
        "consumer_owner": "owner",
        "entries": {"owner": FakeEntry("owner"), "secondary": FakeEntry("secondary")},
        "forwarded": {
            "owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS,
            "secondary": ENTRY_PLATFORMS,
        },
        "learn_tasks": {},
        "store": store,
    }
    hass = FakeHass(domain_data)
    entry = type(
        "Entry",
        (),
        {"entry_id": "owner", "data": {CONF_IEEE: "00:11"}},
    )()

    asyncio.run(async_remove_entry(hass, entry))

    assert store.data["transmitters"] == {}
    assert store.saved is True


def test_store_reconcile_prunes_orphans_and_list_commands_shows_valid_transmitters() -> None:
    store = IRRegistryStore.__new__(IRRegistryStore)
    store.data = {
        "transmitters": {
            "0011": {"ieee": "00:11", "name": "Living", "enabled": True},
            "0022": {"ieee": "00:22", "name": "Bedroom", "enabled": False},
            "dead": {"ieee": "de:ad", "name": "Orphan", "enabled": True},
        },
        "locations": {},
    }
    store.async_save = AsyncMock()

    asyncio.run(store.async_reconcile_transmitters({"0011", "0022"}))

    assert set(store.data["transmitters"]) == {"0011", "0022"}
    listed = store.list_commands()["transmitters"]
    assert listed == [
        {"key": "0011", "ieee": "00:11", "name": "Living", "enabled": True},
        {"key": "0022", "ieee": "00:22", "name": "Bedroom", "enabled": False},
    ]


def test_store_update_device_rejects_unknown_transmitter_id() -> None:
    store = IRRegistryStore.__new__(IRRegistryStore)
    store.data = {
        "transmitters": {"0011": {"ieee": "00:11", "enabled": True}},
        "locations": {
            "living": {
                "devices": {
                    "tv": {
                        "name": "TV",
                        "type": "generic",
                        "preferred_domain": "remote",
                        "transmitter_id": None,
                        "commands": {},
                    }
                }
            }
        },
    }
    store.async_save = AsyncMock()

    with pytest.raises(IRLearningHubError, match="Unknown IR transmitter: garbage"):
        asyncio.run(
            store.update_device(
                "living",
                "tv",
                transmitter_id="garbage",
            )
        )


def test_resolved_entity_id_can_be_saved_as_canonical_transmitter_id(monkeypatch) -> None:
    store = IRRegistryStore.__new__(IRRegistryStore)
    store.data = {
        "transmitters": {"0011": {"ieee": "00:11", "enabled": True}},
        "locations": {
            "living": {
                "devices": {
                    "tv": {
                        "name": "TV",
                        "type": "generic",
                        "preferred_domain": "remote",
                        "transmitter_id": None,
                        "commands": {},
                    }
                }
            }
        },
    }
    store.async_save = AsyncMock()
    registry = type(
        "Registry",
        (),
        {
            "async_get": lambda self, entity_id: type(
                "EntityEntry",
                (),
                {
                    "domain": "infrared",
                    "platform": DOMAIN,
                    "unique_id": "0011",
                },
            )()
        },
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.er.async_get",
        lambda hass: registry,
    )

    transmitter_id = resolve_transmitter_ref(
        object(), store, "infrared.ir_transmitter_00_11"
    )
    asyncio.run(
        store.update_device(
            "living",
            "tv",
            transmitter_id=transmitter_id,
        )
    )

    assert store.data["locations"]["living"]["devices"]["tv"]["transmitter_id"] == "0011"


def test_update_device_service_can_clear_transmitter_id() -> None:
    update_device = AsyncMock()
    store = type(
        "Store",
        (),
        {
            "resolve_transmitter": lambda self, transmitter_id=None: {"ieee": "00:11"},
            "update_device": update_device,
        },
    )()
    hass = FakeHass(
        {
            "store": store,
            "adapter": object(),
            "status": type("Status", (), {"async_set": lambda self, *args, **kwargs: None})(),
            "learn_tasks": {},
        }
    )

    _register_services(hass)
    callback = hass.services.registered[(DOMAIN, "update_device")]

    asyncio.run(
        callback(
            type(
                "Call",
                (),
                {
                    "data": {
                        "location_id": "living",
                        "ir_device_id": "tv",
                        "transmitter_id": "",
                    }
                },
            )()
        )
    )

    update_device.assert_awaited_once_with(
        "living",
        "tv",
        name=None,
        device_type=None,
        preferred_domain=None,
        transmitter_id="",
    )


def test_remote_manager_coalesces_trailing_edge_reconcile(monkeypatch) -> None:
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
            return Task()

    manager = RemoteEntityManager(Hass(), FakeStore(), lambda entities: None)
    run_order = []

    async def fake_reconcile(self):
        async with self._reconcile_lock:
            while True:
                self._reconcile_pending = False
                run_order.append("run")
                if len(run_order) == 1:
                    self.async_schedule_reconcile()
                if not self._reconcile_pending:
                    break

    monkeypatch.setattr(RemoteEntityManager, "async_reconcile", fake_reconcile, raising=False)
    manager._reconcile_task = Task()

    asyncio.run(fake_reconcile(manager))

    assert run_order == ["run", "run"]


def test_remove_non_owner_does_not_reload_or_change_owner() -> None:
    domain_data = {
        "consumer_owner": "owner",
        "entries": {"owner": FakeEntry("owner"), "secondary": FakeEntry("secondary")},
        "forwarded": {
            "owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS,
            "secondary": ENTRY_PLATFORMS,
        },
        "learn_tasks": {},
    }
    hass = FakeHass(domain_data)

    asyncio.run(async_remove_entry(hass, FakeEntry("secondary")))

    assert domain_data["consumer_owner"] == "owner"
    assert set(domain_data["entries"]) == {"owner"}
    assert set(domain_data["forwarded"]) == {"owner"}
    assert hass.config_entries.reloads == []
    assert DOMAIN in hass.data


def test_remove_last_entry_tears_down_services_and_domain_data() -> None:
    task = type("Task", (), {"cancelled": False})()
    task.cancel = lambda: setattr(task, "cancelled", True)
    domain_data = {
        "consumer_owner": "owner",
        "entries": {"owner": FakeEntry("owner")},
        "forwarded": {"owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS},
        "learn_tasks": {"00:11": task},
    }
    hass = FakeHass(domain_data)

    asyncio.run(async_remove_entry(hass, FakeEntry("owner")))

    assert task.cancelled
    assert hass.services.removed == [
        (DOMAIN, service) for service in REGISTERED_SERVICES
    ]
    assert DOMAIN not in hass.data


def test_unload_entry_uses_forwarded_platforms_not_current_owner() -> None:
    domain_data = {
        "consumer_owner": "secondary",
        "entries": {"owner": FakeEntry("owner"), "secondary": FakeEntry("secondary")},
        "forwarded": {
            "owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS,
            "secondary": ENTRY_PLATFORMS,
        },
    }
    hass = FakeHass(domain_data)

    assert asyncio.run(async_unload_entry(hass, FakeEntry("secondary"))) is True

    assert hass.config_entries.unloaded == [("secondary", ENTRY_PLATFORMS)]
    assert domain_data["consumer_owner"] == "secondary"
    assert set(domain_data["entries"]) == {"owner", "secondary"}
    assert hass.services.removed == []


def test_reload_unload_keeps_owner_entries_and_services() -> None:
    domain_data = {
        "consumer_owner": "owner",
        "entries": {"owner": FakeEntry("owner")},
        "forwarded": {"owner": ENTRY_PLATFORMS + CONSUMER_PLATFORMS},
        "learn_tasks": {},
    }
    hass = FakeHass(domain_data)

    assert asyncio.run(async_unload_entry(hass, FakeEntry("owner"))) is True

    assert hass.config_entries.unloaded == [
        ("owner", ENTRY_PLATFORMS + CONSUMER_PLATFORMS)
    ]
    assert domain_data["consumer_owner"] == "owner"
    assert set(domain_data["entries"]) == {"owner"}
    assert DOMAIN in hass.data
    assert hass.services.removed == []


def test_remote_manager_reconcile_is_idempotent_and_removes_missing_entities(monkeypatch) -> None:
    store = FakeStore()
    store.data["locations"] = {
        "living": {
            "devices": {
                "tv": {
                    "name": "TV",
                    "type": "generic",
                    "preferred_domain": "remote",
                    "commands": {"power_toggle": {"feature": "power_toggle"}},
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
    entity = manager.entities["living__tv"]
    entity.entity_id = "remote.tv"
    entity.async_remove = remove_mock
    removed_entity_ids = []
    removed_device_ids = []

    class FakeEntityRegistry:
        def __init__(self) -> None:
            self.entities = {
                "remote.tv": type("EntityEntry", (), {"device_id": "device-1"})()
            }

        def async_get(self, entity_id):
            return self.entities.get(entity_id)

        def async_remove(self, entity_id):
            removed_entity_ids.append(entity_id)
            self.entities.pop(entity_id, None)

    class FakeDeviceRegistry:
        def async_get_device(self, identifiers):
            if identifiers == {(DOMAIN, "living__tv")}:
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

    remove_mock.assert_awaited_once()
    assert removed_entity_ids == ["remote.tv"]
    assert removed_device_ids == ["device-1"]
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
