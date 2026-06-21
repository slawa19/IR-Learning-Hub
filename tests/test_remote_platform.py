"""Pytest tests for HA-backed remote and emitter pieces."""

from __future__ import annotations

import importlib.util
import asyncio
from types import MappingProxyType
from unittest.mock import AsyncMock
import unittest

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from homeassistant.exceptions import ServiceValidationError

from custom_components.ir_learning_hub.const import (
    CONF_CLUSTER_ID,
    CONF_ENDPOINT_ID,
    CONF_IEEE,
    CONF_LEARN_REASSERT_INTERVAL,
    CONF_LEARN_TIMEOUT,
    CONF_PROFILE,
    DEFAULT_CLUSTER_ID,
    DEFAULT_ENDPOINT_ID,
    DEFAULT_LEARN_REASSERT_INTERVAL,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_PROFILE,
    DOMAIN,
    HUB_ENTRY_DATA,
    HUB_TITLE,
    TRANSMITTER_SUBENTRY_TYPE,
)
from custom_components.ir_learning_hub.errors import IRLearningHubError
from custom_components.ir_learning_hub.device_profiles import get_profile
from custom_components.ir_learning_hub import (
    PLATFORMS,
    REGISTERED_SERVICES,
    FRONTEND_URL,
    _async_handle_entry_update,
    _async_sync_frontend_resource,
    _frontend_resource_url,
    _reap_orphan_virtual_devices,
    _register_services,
    _async_migrate_legacy_entries_to_hub,
    async_remove_config_entry_device,
    resolve_transmitter_ref,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    _register_transmitter_device,
)
from homeassistant.config_entries import ConfigSubentry
from custom_components.ir_learning_hub.infrared import (
    IRLearningHubInfraredEmitter,
    async_setup_entry as async_setup_infrared_entry,
    _transmitter_device_info,
)
from custom_components.ir_learning_hub.ir_command import ZosungCommand
from custom_components.ir_learning_hub.registry_runtime import EntitySpec, desired_entities
from custom_components.ir_learning_hub.remote import (
    IRLearningHubRemoteEntity,
    RemoteEntityManager,
    async_setup_entry as async_setup_remote_entry,
    async_send_registry_command,
)
from custom_components.ir_learning_hub.storage import IRRegistryStore
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE


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
    def __init__(self, entry_id: str, data=None, subentries=None) -> None:
        self.entry_id = entry_id
        self.data = data or {}
        self.title = f"Entry {entry_id}"
        self.subentries = MappingProxyType(
            {subentry.subentry_id: subentry for subentry in (subentries or [])}
        )
        self._unloaders = []
        self.update_listeners = []

    def get_subentries_of_type(self, subentry_type):
        return [
            subentry
            for subentry in self.subentries.values()
            if subentry.subentry_type == subentry_type
        ]

    def add_update_listener(self, listener):
        self.update_listeners.append(listener)
        return lambda: self.update_listeners.remove(listener)

    def async_on_unload(self, callback):
        self._unloaders.append(callback)


class FakeConfigEntries:
    def __init__(self) -> None:
        self.forwarded = []
        self.unloaded = []
        self.reloads = []
        self._entries = []
        self.removed = []
        self.updated = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, list(platforms)))
        return True

    def async_schedule_reload(self, entry_id):
        self.reloads.append(entry_id)

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_get_known_entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise KeyError(entry_id)

    def async_update_entry(self, entry, **changes):
        if "data" in changes:
            entry.data = changes["data"]
        if "title" in changes:
            entry.title = changes["title"]
        self.updated.append((entry.entry_id, changes))
        return True

    def async_add_subentry(self, entry, subentry):
        entry.subentries = MappingProxyType(
            dict(entry.subentries) | {subentry.subentry_id: subentry}
        )
        return True

    async def async_remove(self, entry_id):
        self.removed.append(entry_id)
        self._entries = [entry for entry in self._entries if entry.entry_id != entry_id]
        return {"require_restart": False}


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
    def __init__(self) -> None:
        self.data = {"locations": {}}

    async def async_load(self):
        return None

    async def async_upsert_transmitter_from_entry(self, entry_data):
        return entry_data[CONF_IEEE].replace(":", "").lower()

    async def async_reconcile_transmitters(self, valid_keys):
        self.valid_keys = valid_keys


class FakeRemovalStore:
    def __init__(self) -> None:
        self.data = {"transmitters": {"0011": {"ieee": "00:11"}}}
        self.saved = False

    async def async_save(self) -> None:
        self.saved = True


class FakeLovelaceResources:
    def __init__(self, items=None) -> None:
        self._items = list(items or [])
        self.created = []
        self.updated = []
        self.deleted = []

    async def async_get_info(self):
        return {"resources": len(self._items)}

    def async_items(self):
        return list(self._items)

    async def async_create_item(self, data):
        created = {"id": f"new-{len(self._items)+1}", "type": data["res_type"], "url": data["url"]}
        self._items.append(created)
        self.created.append(created)
        return created

    async def async_update_item(self, item_id, updates):
        for item in self._items:
            if item["id"] == item_id:
                item.update(updates)
                self.updated.append((item_id, updates))
                return item
        raise KeyError(item_id)

    async def async_delete_item(self, item_id):
        self._items = [item for item in self._items if item["id"] != item_id]
        self.deleted.append(item_id)


def make_transmitter_subentry(
    ieee: str,
    *,
    subentry_id: str,
    title: str | None = None,
):
    return ConfigSubentry(
        data=MappingProxyType(
            {
                CONF_IEEE: ieee,
                CONF_PROFILE: DEFAULT_PROFILE,
                CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
                CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
                CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
                CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
            }
        ),
        subentry_id=subentry_id,
        subentry_type=TRANSMITTER_SUBENTRY_TYPE,
        title=title or ieee,
        unique_id=ieee.replace(":", "").lower(),
    )


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


def test_emitter_logs_dispatch_without_claiming_delivery(caplog) -> None:
    store = FakeStore()
    adapter = type("Adapter", (), {"async_send": AsyncMock()})()
    emitter = IRLearningHubInfraredEmitter(
        store,
        adapter,
        "0011",
        {CONF_IEEE: "00:11"},
    )

    with caplog.at_level("DEBUG"):
        asyncio.run(emitter.async_send_command(ZosungCommand("abc")))

    assert "IR send dispatched to ZHA (delivery not confirmed)" in caplog.text
    assert "00:11" in caplog.text


def test_emitter_device_info_attaches_to_registered_transmitter_device() -> None:
    device_info = _transmitter_device_info("0011", {CONF_IEEE: "00:11"})

    assert device_info == {"identifiers": {(DOMAIN, "0011")}}


def test_infrared_setup_adds_one_emitter_per_transmitter_subentry() -> None:
    store = FakeStore()
    adapter = object()
    entry = FakeEntry(
        "hub",
        data=HUB_ENTRY_DATA,
        subentries=[
            make_transmitter_subentry("00:11", subentry_id="sub-1"),
            make_transmitter_subentry("00:22", subentry_id="sub-2"),
        ],
    )
    hass = FakeHass({"store": store, "adapter": adapter})
    added = []

    def async_add_entities(entities, update_before_add=False, *, config_subentry_id=None):
        added.append((config_subentry_id, entities))

    asyncio.run(async_setup_infrared_entry(hass, entry, async_add_entities))

    assert [item[0] for item in added] == ["sub-1", "sub-2"]
    assert [item[1][0].unique_id for item in added] == ["0011", "0022"]


def test_transmitter_device_registration_owns_ts1201_metadata(monkeypatch) -> None:
    calls = []
    updates = []
    registry = type(
        "DeviceRegistry",
        (),
        {
            "async_get_or_create": lambda self, **kwargs: (
                calls.append(kwargs)
                or type(
                    "DeviceEntry",
                    (),
                    {
                        "id": "device-1",
                        "config_entries_subentries": {"entry-1": {"sub-1"}},
                    },
                )()
            ),
            "async_update_device": lambda self, device_id, **kwargs: updates.append(
                (device_id, kwargs)
            ),
        },
    )()
    entry = type(
        "Entry",
        (),
        {"entry_id": "entry-1"},
    )()
    subentry = type(
        "Subentry",
        (),
        {
            "subentry_id": "sub-1",
            "data": {CONF_IEEE: "AA:BB:CC"},
        },
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_get",
        lambda hass: registry,
    )

    _register_transmitter_device(object(), entry, subentry, "aa_bb_cc")

    assert calls == [
        {
            "config_entry_id": "entry-1",
            "config_subentry_id": "sub-1",
            "identifiers": {(DOMAIN, "aa_bb_cc")},
            "via_device": ("zha", "aa:bb:cc"),
            "name": "IR transmitter aa:bb:cc",
            "manufacturer": "Tuya",
            "model": "TS1201 / MOES UFO-R11",
        }
    ]
    assert updates == []


def test_transmitter_device_registration_strips_stale_entry_level_association(
    monkeypatch,
) -> None:
    updates = []
    registry = type(
        "DeviceRegistry",
        (),
        {
            "async_get_or_create": lambda self, **kwargs: type(
                "DeviceEntry",
                (),
                {
                    "id": "device-1",
                    "config_entries_subentries": {"entry-1": {None, "sub-1"}},
                },
            )(),
            "async_update_device": lambda self, device_id, **kwargs: updates.append(
                (device_id, kwargs)
            ),
        },
    )()
    entry = type("Entry", (), {"entry_id": "entry-1"})()
    subentry = type(
        "Subentry",
        (),
        {"subentry_id": "sub-1", "data": {CONF_IEEE: "AA:BB:CC"}},
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_get",
        lambda hass: registry,
    )

    _register_transmitter_device(object(), entry, subentry, "aa_bb_cc")

    assert updates == [
        (
            "device-1",
            {
                "add_config_entry_id": "entry-1",
                "add_config_subentry_id": "sub-1",
                "remove_config_entry_id": "entry-1",
                "remove_config_subentry_id": None,
            },
        )
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


def test_remote_platform_sets_up_on_hub_entry_without_owner_gate() -> None:
    hass = FakeHass({"store": FakeStore()})
    entry = FakeEntry("hub", data=HUB_ENTRY_DATA)
    added = []

    asyncio.run(async_setup_remote_entry(hass, entry, lambda entities: added.extend(entities)))

    assert "remote_manager" in hass.data[DOMAIN]


def test_setup_entry_tracks_hub_platforms_and_transmitter_subentries(monkeypatch) -> None:
    hass = FakeHass()
    entry = FakeEntry(
        "hub",
        data=HUB_ENTRY_DATA,
        subentries=[
            make_transmitter_subentry("00:11", subentry_id="sub-1"),
            make_transmitter_subentry("00:22", subentry_id="sub-2"),
        ],
    )
    hass.config_entries._entries = [entry]
    registered = []
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
        lambda hass, entry, subentry, transmitter_id: registered.append(
            (subentry.subentry_id, transmitter_id)
        ),
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True

    domain_data = hass.data[DOMAIN]
    assert hass.config_entries.forwarded == [("hub", PLATFORMS)]
    assert domain_data["store"].valid_keys == {"0011", "0022"}
    assert domain_data["entry_subentry_ids"]["hub"] == {"0011", "0022"}
    assert registered == [("sub-1", "0011"), ("sub-2", "0022")]
    assert len(entry.update_listeners) == 1


def test_setup_entry_reaps_orphan_virtual_devices(monkeypatch) -> None:
    hass = FakeHass()
    entry = FakeEntry("hub", data=HUB_ENTRY_DATA)
    hass.config_entries._entries = [entry]
    setup_store = FakeSetupStore()
    setup_store.data = {
        "locations": {
            "living": {
                "devices": {"kept": {"name": "Kept", "commands": {}}},
            }
        }
    }
    removed = []
    registry = type(
        "DeviceRegistry",
        (),
        {
            "async_remove_device": lambda self, device_id: removed.append(device_id),
        },
    )()
    devices = [
        type("DeviceEntry", (), {"id": "dev-1", "identifiers": {(DOMAIN, "living__stale")}})(),
        type("DeviceEntry", (), {"id": "dev-2", "identifiers": {(DOMAIN, "living__kept")}})(),
        type("DeviceEntry", (), {"id": "dev-3", "identifiers": {(DOMAIN, "0011")}})(),
    ]
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.IRRegistryStore",
        lambda hass: setup_store,
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
        "custom_components.ir_learning_hub.dr.async_get",
        lambda hass: registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_entries_for_config_entry",
        lambda registry, entry_id: devices,
    )

    assert asyncio.run(async_setup_entry(hass, entry)) is True

    assert removed == ["dev-1"]


def test_sync_frontend_resource_creates_cache_busted_module_url(tmp_path) -> None:
    card_path = tmp_path / "ir-learning-hub-card.js"
    card_path.write_text("// card", encoding="utf-8")
    resources = FakeLovelaceResources()
    hass = type(
        "Hass",
        (),
        {"data": {LOVELACE_DATA: type("LovelaceData", (), {"resource_mode": MODE_STORAGE, "resources": resources})()}},
    )()

    asyncio.run(_async_sync_frontend_resource(hass, card_path))

    assert len(resources.created) == 1
    assert resources.created[0]["type"] == "module"
    assert resources.created[0]["url"] == _frontend_resource_url(card_path)


def test_sync_frontend_resource_updates_existing_url_and_removes_duplicates(tmp_path) -> None:
    card_path = tmp_path / "ir-learning-hub-card.js"
    card_path.write_text("// card", encoding="utf-8")
    resources = FakeLovelaceResources(
        [
            {"id": "1", "type": "module", "url": FRONTEND_URL},
            {"id": "2", "type": "module", "url": f"{FRONTEND_URL}?v=old"},
            {"id": "3", "type": "module", "url": "/other.js"},
        ]
    )
    hass = type(
        "Hass",
        (),
        {"data": {LOVELACE_DATA: type("LovelaceData", (), {"resource_mode": MODE_STORAGE, "resources": resources})()}},
    )()

    asyncio.run(_async_sync_frontend_resource(hass, card_path))

    assert resources.updated == [("1", {"url": _frontend_resource_url(card_path)})]
    assert resources.deleted == ["2"]


def test_entry_update_listener_reloads_hub_only_on_subentry_change() -> None:
    hass = FakeHass({"entry_subentry_ids": {"hub": {"0011"}}})
    entry = FakeEntry(
        "hub",
        data=HUB_ENTRY_DATA,
        subentries=[make_transmitter_subentry("00:11", subentry_id="sub-1")],
    )

    asyncio.run(_async_handle_entry_update(hass, entry))

    assert hass.config_entries.reloads == []

    entry.subentries = MappingProxyType(
        dict(entry.subentries)
        | {"sub-2": make_transmitter_subentry("00:22", subentry_id="sub-2")}
    )
    asyncio.run(_async_handle_entry_update(hass, entry))

    assert hass.config_entries.reloads == ["hub"]
    assert hass.data[DOMAIN]["entry_subentry_ids"]["hub"] == {"0011", "0022"}


def test_reap_orphan_virtual_devices_is_idempotent(monkeypatch) -> None:
    removed = []
    devices = [
        type("DeviceEntry", (), {"id": "dev-1", "identifiers": {(DOMAIN, "living__stale")}})(),
        type("DeviceEntry", (), {"id": "dev-2", "identifiers": {(DOMAIN, "living__kept")}})(),
    ]

    def remove_device(device_id):
        removed.append(device_id)
        devices[:] = [device for device in devices if device.id != device_id]

    registry = type(
        "DeviceRegistry",
        (),
        {"async_remove_device": lambda self, device_id: remove_device(device_id)},
    )()
    store = type(
        "Store",
        (),
        {
            "data": {
                "locations": {
                    "living": {"devices": {"kept": {"name": "Kept", "commands": {}}}}
                }
            }
        },
    )()
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_get",
        lambda hass: registry,
    )
    monkeypatch.setattr(
        "custom_components.ir_learning_hub.dr.async_entries_for_config_entry",
        lambda registry, entry_id: devices,
    )

    _reap_orphan_virtual_devices(object(), FakeEntry("hub"), store)
    _reap_orphan_virtual_devices(object(), FakeEntry("hub"), store)

    assert removed == ["dev-1"]


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


def test_async_setup_migrates_single_legacy_entry_to_hub_subentry() -> None:
    entry = FakeEntry(
        "legacy-1",
        data={
            CONF_IEEE: "00:11",
            CONF_PROFILE: DEFAULT_PROFILE,
            CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
            CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
            CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
            CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
        },
    )
    hass = FakeHass()
    hass.config_entries._entries = [entry]

    assert asyncio.run(async_setup(hass, {})) is True

    assert entry.data == HUB_ENTRY_DATA
    assert entry.title == HUB_TITLE
    subentries = entry.get_subentries_of_type(TRANSMITTER_SUBENTRY_TYPE)
    assert len(subentries) == 1
    assert subentries[0].unique_id == "0011"
    assert hass.config_entries.removed == []


def test_legacy_migration_merges_multiple_entries_into_one_hub() -> None:
    hub = FakeEntry(
        "legacy-1",
        data={
            CONF_IEEE: "00:11",
            CONF_PROFILE: DEFAULT_PROFILE,
            CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
            CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
            CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
            CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
        },
    )
    secondary = FakeEntry(
        "legacy-2",
        data={
            CONF_IEEE: "00:22",
            CONF_PROFILE: DEFAULT_PROFILE,
            CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
            CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
            CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
            CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
        },
    )
    hass = FakeHass()
    hass.config_entries._entries = [hub, secondary]

    asyncio.run(_async_migrate_legacy_entries_to_hub(hass))
    asyncio.run(_async_migrate_legacy_entries_to_hub(hass))

    assert hub.data == HUB_ENTRY_DATA
    assert hub.title == HUB_TITLE
    assert {subentry.unique_id for subentry in hub.get_subentries_of_type(TRANSMITTER_SUBENTRY_TYPE)} == {
        "0011",
        "0022",
    }
    assert hass.config_entries.removed == ["legacy-2"]


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


def test_store_reconcile_skips_empty_valid_key_set() -> None:
    store = IRRegistryStore.__new__(IRRegistryStore)
    store.data = {
        "transmitters": {"0011": {"ieee": "00:11", "enabled": True}},
        "locations": {},
    }
    store.async_save = AsyncMock()

    asyncio.run(store.async_reconcile_transmitters(set()))

    assert set(store.data["transmitters"]) == {"0011"}
    store.async_save.assert_not_awaited()


def test_store_upsert_transmitter_skips_save_when_unchanged() -> None:
    profile = get_profile(DEFAULT_PROFILE)
    store = IRRegistryStore.__new__(IRRegistryStore)
    store.data = {
        "transmitters": {
            "0011": {
                "ieee": "00:11",
                "name": "IR transmitter 00:11",
                "manufacturer": None,
                "model": None,
                "quirk_class": None,
                "profile": DEFAULT_PROFILE,
                "config": {
                    "endpoint_id": DEFAULT_ENDPOINT_ID,
                    "ir_control_cluster": DEFAULT_CLUSTER_ID,
                    "ir_transmit_cluster": profile["ir_transmit_cluster"],
                    "learn_timeout": DEFAULT_LEARN_TIMEOUT,
                    "learn_reassert_interval": DEFAULT_LEARN_REASSERT_INTERVAL,
                },
                "enabled": True,
                "needs_confirmation": False,
            }
        },
        "locations": {},
    }
    store.async_save = AsyncMock()

    transmitter_id = asyncio.run(
        store.async_upsert_transmitter_from_entry(
            {
                CONF_IEEE: "00:11",
                CONF_PROFILE: DEFAULT_PROFILE,
                CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
                CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
                CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
                CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
            }
        )
    )

    assert transmitter_id == "0011"
    store.async_save.assert_not_awaited()


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


def test_remove_config_entry_device_deletes_virtual_registry_device() -> None:
    delete_device = AsyncMock()
    hass = FakeHass({"store": type("Store", (), {"delete_device": delete_device})()})
    device_entry = type(
        "DeviceEntry",
        (),
        {"identifiers": {(DOMAIN, "living__tv")}},
    )()

    result = asyncio.run(async_remove_config_entry_device(hass, FakeEntry("hub"), device_entry))

    assert result is True
    delete_device.assert_awaited_once_with("living", "tv", confirm=True)


def test_remove_config_entry_device_refuses_emitter_device() -> None:
    hass = FakeHass({"store": object()})
    device_entry = type(
        "DeviceEntry",
        (),
        {"identifiers": {(DOMAIN, "0011")}},
    )()

    result = asyncio.run(async_remove_config_entry_device(hass, FakeEntry("hub"), device_entry))

    assert result is False


def test_remove_config_entry_device_ignores_missing_virtual_registry_device() -> None:
    hass = FakeHass(
        {
            "store": type(
                "Store",
                (),
                {
                    "delete_device": AsyncMock(
                        side_effect=IRLearningHubError(
                            "command_not_found",
                            "IR device tv was not found",
                        )
                    )
                },
            )()
        }
    )
    device_entry = type(
        "DeviceEntry",
        (),
        {"identifiers": {(DOMAIN, "living__tv")}},
    )()

    result = asyncio.run(async_remove_config_entry_device(hass, FakeEntry("hub"), device_entry))

    assert result is True


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


def test_async_unload_entry_unloads_all_platforms_and_tears_down_domain() -> None:
    task = type("Task", (), {"cancelled": False})()
    task.cancel = lambda: setattr(task, "cancelled", True)
    domain_data = {
        "learn_tasks": {"00:11": task},
    }
    hass = FakeHass(domain_data)
    entry = FakeEntry("hub", data=HUB_ENTRY_DATA)

    assert asyncio.run(async_unload_entry(hass, entry)) is True

    assert task.cancelled
    assert hass.config_entries.unloaded == [("hub", PLATFORMS)]
    assert hass.services.removed == [
        (DOMAIN, service) for service in REGISTERED_SERVICES
    ]
    assert DOMAIN not in hass.data


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
