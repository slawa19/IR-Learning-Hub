"""Tests for ZHA compatibility helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from custom_components.ir_learning_hub.const import (
    DEFAULT_CLUSTER_ID,
    DEFAULT_PROFILE,
    ERROR_CLUSTER_NOT_FOUND,
    ERROR_ZHA_UNAVAILABLE,
)
from custom_components.ir_learning_hub.errors import IRLearningHubError
from custom_components.ir_learning_hub.zha_compat import (
    detect_ir_control_cluster,
    find_zha_cluster,
    get_zha_device_proxy,
    iter_zha_nested_devices,
)


def test_get_zha_device_proxy_wraps_helper(monkeypatch) -> None:
    helper_module = types.ModuleType("homeassistant.components.zha.helpers")
    helper_module.async_get_zha_device_proxy = lambda hass, device_id: ("proxy", device_id)
    monkeypatch.setitem(sys.modules, "homeassistant.components.zha.helpers", helper_module)

    assert get_zha_device_proxy(object(), "dev-1") == ("proxy", "dev-1")


def test_get_zha_device_proxy_normalizes_helper_exception(monkeypatch) -> None:
    helper_module = types.ModuleType("homeassistant.components.zha.helpers")

    def raise_error(hass, device_id):
        raise RuntimeError("nope")

    helper_module.async_get_zha_device_proxy = raise_error
    monkeypatch.setitem(sys.modules, "homeassistant.components.zha.helpers", helper_module)

    with pytest.raises(IRLearningHubError) as err:
        get_zha_device_proxy(object(), "dev-1")

    assert err.value.code == ERROR_ZHA_UNAVAILABLE


def test_iter_zha_nested_devices_dedupes() -> None:
    inner = type("Device", (), {})()
    middle = type("Device", (), {"device": inner})()
    outer = type("Proxy", (), {"device": middle})()
    inner.device = middle

    assert iter_zha_nested_devices(outer) == [outer, middle, inner]


def test_find_zha_cluster_from_proxy_itself() -> None:
    cluster = object()
    endpoint = type("Endpoint", (), {"in_clusters": {DEFAULT_CLUSTER_ID: cluster}})()
    proxy = type("Proxy", (), {"endpoints": {1: endpoint}})()

    assert find_zha_cluster(proxy, 1, DEFAULT_CLUSTER_ID) is cluster


def test_find_zha_cluster_from_in_clusters() -> None:
    cluster = object()
    endpoint = type("Endpoint", (), {"in_clusters": {DEFAULT_CLUSTER_ID: cluster}})()
    device = type("Device", (), {"endpoints": {1: endpoint}})()
    proxy = type("Proxy", (), {"device": device})()

    assert find_zha_cluster(proxy, 1, DEFAULT_CLUSTER_ID) is cluster


def test_find_zha_cluster_from_named_cluster() -> None:
    cluster = type("Cluster", (), {"cluster_id": DEFAULT_CLUSTER_ID})()
    endpoint = type("Endpoint", (), {"in_clusters": {}, "zosung_ircontrol": cluster})()
    device = type("Device", (), {"endpoints": {1: endpoint}})()
    proxy = type("Proxy", (), {"device": device})()

    assert find_zha_cluster(proxy, 1, DEFAULT_CLUSTER_ID) is cluster


def test_find_zha_cluster_missing_raises_cluster_not_found() -> None:
    proxy = type("Proxy", (), {"device": type("Device", (), {"endpoints": {}})()})()

    with pytest.raises(IRLearningHubError) as err:
        find_zha_cluster(proxy, 1, DEFAULT_CLUSTER_ID)

    assert err.value.code == ERROR_CLUSTER_NOT_FOUND


def test_find_zha_cluster_unsupported_proxy_shape_raises_zha_unavailable() -> None:
    proxy = object()

    with pytest.raises(IRLearningHubError) as err:
        find_zha_cluster(proxy, 1, DEFAULT_CLUSTER_ID)

    assert err.value.code == ERROR_ZHA_UNAVAILABLE


def test_detect_ir_control_cluster() -> None:
    cluster = object()
    endpoint = type("Endpoint", (), {"in_clusters": {DEFAULT_CLUSTER_ID: cluster}})()
    device = type("Device", (), {"endpoints": {1: endpoint}})()
    proxy = type("Proxy", (), {"device": device})()

    assert detect_ir_control_cluster(proxy, DEFAULT_PROFILE) == (1, DEFAULT_CLUSTER_ID)


def test_detect_ir_control_cluster_unsupported_proxy_shape_raises_zha_unavailable() -> None:
    with pytest.raises(IRLearningHubError) as err:
        detect_ir_control_cluster(object(), DEFAULT_PROFILE)

    assert err.value.code == ERROR_ZHA_UNAVAILABLE
