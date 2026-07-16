"""Tests for per-transmitter IR command dispatching."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest

if importlib.util.find_spec("homeassistant") is None:
    raise unittest.SkipTest("homeassistant is not installed")

import pytest

from custom_components.ir_learning_hub.const import (
    ERROR_COMMAND_EXPIRED,
    ERROR_DISPATCHER_STOPPED,
    ERROR_QUEUE_FULL,
    ERROR_SEND_FAILED,
    STATUS_DELIVERY_FAILED,
    STATUS_DISPATCHED_UNCONFIRMED,
    STATUS_DISPATCHING,
    STATUS_EXPIRED,
    STATUS_QUEUE_FULL,
    STATUS_QUEUED,
)
from custom_components.ir_learning_hub.dispatcher import (
    CommandContext,
    IRCommandDispatcher,
)
from custom_components.ir_learning_hub.errors import IRLearningHubError


class FakeStatus:
    def __init__(self) -> None:
        self.events = []

    def async_set(self, state, **kwargs):
        self.events.append((state, kwargs))


def context(transmitter_id="tx1") -> CommandContext:
    return CommandContext(
        request_id=f"req-{transmitter_id}",
        transmitter_id=transmitter_id,
        location_id="living",
        ir_device_id="amp",
        command_id="power",
        source="service",
    )


async def wait_for(predicate, *, timeout=1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition was not reached")
        await asyncio.sleep(0.001)


def test_dispatcher_serializes_one_transmitter() -> None:
    async def run() -> None:
        active = 0
        max_active = 0
        release = asyncio.Event()
        started = 0

        class Adapter:
            async def async_send(self, transmitter, code):
                nonlocal active, max_active, started
                active += 1
                started += 1
                max_active = max(max_active, active)
                await release.wait()
                active -= 1

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        task1 = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        task2 = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "b", context=context())
        )
        await wait_for(lambda: started == 1)
        release.set()
        await asyncio.gather(task1, task2)

        assert max_active == 1

    asyncio.run(run())


def test_dispatcher_isolates_different_transmitters() -> None:
    async def run() -> None:
        active = 0
        max_active = 0
        release = asyncio.Event()

        class Adapter:
            async def async_send(self, transmitter, code):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                await release.wait()
                active -= 1

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        task1 = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context("tx1"))
        )
        task2 = asyncio.create_task(
            dispatcher.async_send("tx2", {"ieee": "00:22"}, "b", context=context("tx2"))
        )
        await wait_for(lambda: max_active == 2)
        release.set()
        await asyncio.gather(task1, task2)

    asyncio.run(run())


def test_dispatcher_expires_before_adapter_call() -> None:
    async def run() -> None:
        calls = 0
        status = FakeStatus()

        class Adapter:
            async def async_send(self, transmitter, code):
                nonlocal calls
                calls += 1

        dispatcher = IRCommandDispatcher(Adapter(), status, ttl_seconds=-1)

        with pytest.raises(IRLearningHubError) as err:
            await dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())

        assert err.value.code == ERROR_COMMAND_EXPIRED
        assert calls == 0
        assert status.events[-1][0] == STATUS_EXPIRED

    asyncio.run(run())


def test_dispatcher_rejects_full_backlog() -> None:
    async def run() -> None:
        release = asyncio.Event()
        status = FakeStatus()

        class Adapter:
            async def async_send(self, transmitter, code):
                await release.wait()

        dispatcher = IRCommandDispatcher(Adapter(), status, max_backlog=1)
        task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        await wait_for(
            lambda: bool(status.events)
            and status.events[-1][0] == STATUS_DISPATCHING
        )

        with pytest.raises(IRLearningHubError) as err:
            await dispatcher.async_send("tx1", {"ieee": "00:11"}, "b", context=context())

        assert err.value.code == ERROR_QUEUE_FULL
        assert status.events[-1][0] == STATUS_QUEUE_FULL
        release.set()
        await task

    asyncio.run(run())


def test_dispatcher_reports_delivery_failure() -> None:
    async def run() -> None:
        status = FakeStatus()

        class Adapter:
            async def async_send(self, transmitter, code):
                raise IRLearningHubError(ERROR_SEND_FAILED, "boom")

        dispatcher = IRCommandDispatcher(Adapter(), status)

        with pytest.raises(IRLearningHubError) as err:
            await dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())

        assert err.value.code == ERROR_SEND_FAILED
        assert status.events[-1][0] == STATUS_DELIVERY_FAILED
        assert status.events[-1][1]["error"] == ERROR_SEND_FAILED

    asyncio.run(run())


def test_dispatcher_success_status_and_response_metadata() -> None:
    async def run() -> None:
        status = FakeStatus()

        class Adapter:
            async def async_send(self, transmitter, code):
                return None

        dispatcher = IRCommandDispatcher(Adapter(), status)
        result = await dispatcher.async_send(
            "tx1",
            {"ieee": "00:11"},
            "a",
            context=context(),
        )

        assert result.status == STATUS_DISPATCHED_UNCONFIRMED
        assert result.delivery_confirmed is False
        assert result.request_id == "req-tx1"
        assert result.transmitter_id == "tx1"
        assert result.queue_wait_ms >= 0
        assert result.command_age_ms >= result.queue_wait_ms
        assert result.queue_depth == 1
        assert [event[0] for event in status.events] == [
            STATUS_QUEUED,
            STATUS_DISPATCHING,
            STATUS_DISPATCHED_UNCONFIRMED,
        ]
        final = status.events[-1][1]
        assert final["request_id"] == "req-tx1"
        assert final["dispatch_status"] == STATUS_DISPATCHED_UNCONFIRMED
        assert final["transmitter_id"] == "tx1"
        assert final["location_id"] == "living"
        assert final["ir_device_id"] == "amp"
        assert final["command_id"] == "power"
        assert final["queue_wait_ms"] >= 0
        assert final["command_age_ms"] >= final["queue_wait_ms"]
        assert final["queue_depth"] == 1
        assert final["delivery_confirmed"] is False

    asyncio.run(run())


def test_dispatcher_removes_idle_state_after_success() -> None:
    async def run() -> None:
        class Adapter:
            async def async_send(self, transmitter, code):
                return None

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())

        await dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        await wait_for(lambda: "tx1" not in dispatcher._states)

    asyncio.run(run())


def test_dispatcher_shutdown_fails_pending_but_not_active_future() -> None:
    async def run() -> None:
        release = asyncio.Event()
        calls = []
        status = FakeStatus()

        class Adapter:
            async def async_send(self, transmitter, code):
                calls.append(code)
                await release.wait()

        dispatcher = IRCommandDispatcher(Adapter(), status)
        active_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        pending_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "b", context=context())
        )
        await wait_for(
            lambda: dispatcher._states.get("tx1") is not None
            and dispatcher._states["tx1"].active_command is not None
            and len(dispatcher._states["tx1"].queue) == 1
        )

        dispatcher.shutdown()

        with pytest.raises(IRLearningHubError) as pending_err:
            await pending_task
        assert pending_err.value.code == ERROR_DISPATCHER_STOPPED
        stopped = status.events[-1]
        assert stopped[0] == ERROR_DISPATCHER_STOPPED
        assert stopped[1]["dispatch_status"] == ERROR_DISPATCHER_STOPPED
        assert stopped[1]["error"] == ERROR_DISPATCHER_STOPPED

        release.set()
        result = await active_task
        assert result.status == STATUS_DISPATCHED_UNCONFIRMED
        assert calls == ["a"]

    asyncio.run(run())


def test_dispatcher_cancels_pending_without_sending() -> None:
    async def run() -> None:
        release = asyncio.Event()
        calls = []

        class Adapter:
            async def async_send(self, transmitter, code):
                calls.append(code)
                await release.wait()

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        active_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        pending_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "b", context=context())
        )
        await wait_for(
            lambda: dispatcher._states.get("tx1") is not None
            and dispatcher._states["tx1"].active_command is not None
            and len(dispatcher._states["tx1"].queue) == 1
        )

        pending_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending_task
        assert len(dispatcher._states["tx1"].queue) == 0

        release.set()
        await active_task
        assert calls == ["a"]

    asyncio.run(run())


def test_dispatcher_pending_cancel_same_tick_as_active_completion_is_not_sent() -> None:
    async def run() -> None:
        release = asyncio.Event()
        calls = []

        class Adapter:
            async def async_send(self, transmitter, code):
                calls.append(code)
                await release.wait()

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        active_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        pending_task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "b", context=context())
        )
        await wait_for(
            lambda: dispatcher._states.get("tx1") is not None
            and dispatcher._states["tx1"].active_command is not None
            and len(dispatcher._states["tx1"].queue) == 1
        )

        loop = asyncio.get_running_loop()
        loop.call_soon(release.set)
        loop.call_soon(pending_task.cancel)

        await active_task
        with pytest.raises(asyncio.CancelledError):
            await pending_task
        assert calls == ["a"]

    asyncio.run(run())


def test_dispatcher_cancelling_active_waiter_does_not_cancel_send() -> None:
    async def run() -> None:
        release = asyncio.Event()
        completed = False

        class Adapter:
            async def async_send(self, transmitter, code):
                nonlocal completed
                await release.wait()
                completed = True

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        task = asyncio.create_task(
            dispatcher.async_send("tx1", {"ieee": "00:11"}, "a", context=context())
        )
        await wait_for(
            lambda: dispatcher._states.get("tx1") is not None
            and dispatcher._states["tx1"].active_command is not None
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        release.set()
        await wait_for(lambda: completed)

    asyncio.run(run())


def test_dispatcher_rejects_new_send_after_shutdown() -> None:
    async def run() -> None:
        class Adapter:
            async def async_send(self, transmitter, code):
                raise AssertionError("adapter should not be called after shutdown")

        dispatcher = IRCommandDispatcher(Adapter(), FakeStatus())
        dispatcher.shutdown()

        with pytest.raises(IRLearningHubError) as err:
            await dispatcher.async_send(
                "tx1",
                {"ieee": "00:11"},
                "a",
                context=context(),
            )
        assert err.value.code == ERROR_DISPATCHER_STOPPED

    asyncio.run(run())
