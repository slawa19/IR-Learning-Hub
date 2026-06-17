"""Tests for hub config flow and transmitter subentry flows."""

from __future__ import annotations

import asyncio
import importlib.util
from types import MappingProxyType
import unittest
from unittest.mock import AsyncMock

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

from homeassistant.config_entries import ConfigSubentry

from custom_components.ir_learning_hub.config_flow import (
    IRLearningHubConfigFlow,
    IRLearningHubTransmitterSubentryFlow,
)
from custom_components.ir_learning_hub.const import (
    CONF_CLUSTER_ID,
    CONF_ENDPOINT_ID,
    CONF_IEEE,
    CONF_LEARN_REASSERT_INTERVAL,
    CONF_LEARN_TIMEOUT,
    CONF_PROFILE,
    CONF_ZHA_DEVICE,
    DEFAULT_CLUSTER_ID,
    DEFAULT_ENDPOINT_ID,
    DEFAULT_LEARN_REASSERT_INTERVAL,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_PROFILE,
    HUB_ENTRY_DATA,
    TRANSMITTER_SUBENTRY_TYPE,
)


class FakeEntry:
    def __init__(self, entry_id: str, subentries=None) -> None:
        self.entry_id = entry_id
        self.subentries = MappingProxyType(
            {subentry.subentry_id: subentry for subentry in (subentries or [])}
        )

    def get_subentries_of_type(self, subentry_type):
        return [
            subentry
            for subentry in self.subentries.values()
            if subentry.subentry_type == subentry_type
        ]


class FakeConfigEntries:
    def __init__(self, entry) -> None:
        self._entry = entry

    def async_get_known_entry(self, entry_id):
        assert entry_id == self._entry.entry_id
        return self._entry


class FakeHass:
    def __init__(self, entry=None) -> None:
        self.config = type("Config", (), {"language": "en"})()
        self.config_entries = FakeConfigEntries(entry) if entry else None


def make_subentry(ieee: str, subentry_id: str = "sub-1") -> ConfigSubentry:
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
        title=ieee,
        unique_id=ieee.replace(":", "").lower(),
    )


def test_main_config_flow_creates_hub_with_first_transmitter_subentry(monkeypatch) -> None:
    flow = IRLearningHubConfigFlow()
    flow.hass = FakeHass()
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [])
    monkeypatch.setattr(
        flow,
        "_async_discover_zha_transmitters",
        AsyncMock(
            return_value={
                "dev-1": {
                    CONF_IEEE: "00:11",
                    CONF_PROFILE: DEFAULT_PROFILE,
                    CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
                    CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
                    "label": "Living",
                }
            }
        ),
    )

    result = asyncio.run(
        flow.async_step_user(
            {
                CONF_ZHA_DEVICE: "dev-1",
                CONF_LEARN_TIMEOUT: 45,
                CONF_LEARN_REASSERT_INTERVAL: 9,
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "IR Learning Hub"
    assert result["data"] == HUB_ENTRY_DATA
    assert len(result["subentries"]) == 1
    assert result["subentries"][0] == {
        "data": {
            CONF_IEEE: "00:11",
            CONF_PROFILE: DEFAULT_PROFILE,
            CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
            CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
            CONF_LEARN_TIMEOUT: 45,
            CONF_LEARN_REASSERT_INTERVAL: 9,
        },
        "subentry_type": TRANSMITTER_SUBENTRY_TYPE,
        "title": "Living",
        "unique_id": "0011",
    }


def test_main_config_flow_aborts_when_hub_already_exists(monkeypatch) -> None:
    flow = IRLearningHubConfigFlow()
    flow.hass = FakeHass()
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [object()])

    result = asyncio.run(flow.async_step_user())

    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


def test_transmitter_subentry_flow_creates_second_transmitter(monkeypatch) -> None:
    entry = FakeEntry("hub", [make_subentry("00:11")])
    flow = IRLearningHubTransmitterSubentryFlow()
    flow.hass = FakeHass(entry)
    flow.handler = (entry.entry_id, TRANSMITTER_SUBENTRY_TYPE)
    flow.context = {"source": "user"}
    monkeypatch.setattr(
        flow,
        "_async_discover_zha_transmitters",
        AsyncMock(
            return_value={
                "dev-2": {
                    CONF_IEEE: "00:22",
                    CONF_PROFILE: DEFAULT_PROFILE,
                    CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
                    CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
                    "label": "Bedroom",
                }
            }
        ),
    )

    result = asyncio.run(
        flow.async_step_user(
            {
                CONF_ZHA_DEVICE: "dev-2",
                CONF_LEARN_TIMEOUT: 61,
                CONF_LEARN_REASSERT_INTERVAL: 7,
            }
        )
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Bedroom"
    assert result["data"] == {
        CONF_IEEE: "00:22",
        CONF_PROFILE: DEFAULT_PROFILE,
        CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
        CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
        CONF_LEARN_TIMEOUT: 61,
        CONF_LEARN_REASSERT_INTERVAL: 7,
    }
    assert result["unique_id"] == "0022"


def test_transmitter_subentry_flow_blocks_duplicate_ieee(monkeypatch) -> None:
    entry = FakeEntry("hub", [make_subentry("00:11")])
    flow = IRLearningHubTransmitterSubentryFlow()
    flow.hass = FakeHass(entry)
    flow.handler = (entry.entry_id, TRANSMITTER_SUBENTRY_TYPE)
    flow.context = {"source": "user"}
    monkeypatch.setattr(
        flow,
        "_async_discover_zha_transmitters",
        AsyncMock(
            return_value={
                "dev-1": {
                    CONF_IEEE: "00:11",
                    CONF_PROFILE: DEFAULT_PROFILE,
                    CONF_ENDPOINT_ID: DEFAULT_ENDPOINT_ID,
                    CONF_CLUSTER_ID: DEFAULT_CLUSTER_ID,
                    "label": "Living",
                }
            }
        ),
    )

    result = asyncio.run(
        flow.async_step_user(
            {
                CONF_ZHA_DEVICE: "dev-1",
                CONF_LEARN_TIMEOUT: DEFAULT_LEARN_TIMEOUT,
                CONF_LEARN_REASSERT_INTERVAL: DEFAULT_LEARN_REASSERT_INTERVAL,
            }
        )
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
