"""Per-transmitter IR send dispatcher."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from homeassistant.util import dt as dt_util

from .const import (
    ERROR_COMMAND_EXPIRED,
    ERROR_DISPATCHER_STOPPED,
    ERROR_QUEUE_FULL,
    ERROR_SEND_FAILED,
    STATUS_DELIVERY_FAILED,
    STATUS_DISPATCHED_UNCONFIRMED,
    STATUS_DISPATCHER_STOPPED,
    STATUS_DISPATCHING,
    STATUS_EXPIRED,
    STATUS_QUEUE_FULL,
    STATUS_QUEUED,
)
from .errors import IRLearningHubError
from .status import HubStatus
from .zha_adapter import ZHAAdapter

_LOGGER = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3.0
DEFAULT_MAX_BACKLOG = 8


@dataclass(frozen=True)
class CommandContext:
    """Diagnostic context for one IR dispatch request."""

    request_id: str
    transmitter_id: str
    location_id: str | None
    ir_device_id: str | None
    command_id: str | None
    source: Literal["entity", "service"]


@dataclass(frozen=True)
class CommandDispatchResult:
    """Successful unconfirmed dispatch result."""

    request_id: str
    status: Literal["dispatched_unconfirmed"]
    delivery_confirmed: Literal[False]
    transmitter_id: str
    queue_wait_ms: int
    command_age_ms: int
    queue_depth: int

    def as_response(self) -> dict[str, Any]:
        """Return response data suitable for HA services."""
        return {
            "status": self.status,
            "delivery_confirmed": self.delivery_confirmed,
            "request_id": self.request_id,
            "transmitter_id": self.transmitter_id,
            "queue_wait_ms": self.queue_wait_ms,
            "command_age_ms": self.command_age_ms,
            "queue_depth": self.queue_depth,
        }


@dataclass
class QueuedIRCommand:
    """One queued IR send operation."""

    transmitter: dict[str, Any]
    code: str
    context: CommandContext
    created_monotonic: float
    created_at: Any
    future: asyncio.Future[CommandDispatchResult]


@dataclass
class _TransmitterQueueState:
    queue: deque[QueuedIRCommand] = field(default_factory=deque)
    active: bool = False
    active_command: QueuedIRCommand | None = None
    worker: asyncio.Task | None = None


class IRCommandDispatcher:
    """Serialize IR sends per physical transmitter with TTL and bounded backlog."""

    def __init__(
        self,
        adapter: ZHAAdapter,
        status: HubStatus,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_backlog: int = DEFAULT_MAX_BACKLOG,
    ) -> None:
        """Initialize the dispatcher."""
        self._adapter = adapter
        self._status = status
        self._ttl_seconds = ttl_seconds
        self._max_backlog = max_backlog
        self._lock = asyncio.Lock()
        self._states: dict[str, _TransmitterQueueState] = {}
        self._stopped = False

    async def async_send(
        self,
        transmitter_id: str,
        transmitter: dict[str, Any],
        code: str,
        *,
        context: CommandContext | None = None,
    ) -> CommandDispatchResult:
        """Queue a send and wait until it is dispatched or fails."""
        if context is None:
            context = CommandContext(
                request_id=_new_request_id(),
                transmitter_id=transmitter_id,
                location_id=None,
                ir_device_id=None,
                command_id=None,
                source="service",
            )
        loop = asyncio.get_running_loop()
        command = QueuedIRCommand(
            transmitter=transmitter,
            code=code,
            context=context,
            created_monotonic=time.monotonic(),
            created_at=dt_util.utcnow(),
            future=loop.create_future(),
        )

        async with self._lock:
            if self._stopped:
                raise IRLearningHubError(
                    ERROR_DISPATCHER_STOPPED,
                    "IR command dispatcher is stopped",
                )
            state = self._states.setdefault(transmitter_id, _TransmitterQueueState())
            depth = len(state.queue) + (1 if state.active else 0)
            if depth >= self._max_backlog:
                err = IRLearningHubError(
                    ERROR_QUEUE_FULL,
                    f"IR queue for transmitter {transmitter_id} is full",
                )
                self._set_status(
                    STATUS_QUEUE_FULL,
                    context,
                    dispatch_status=STATUS_QUEUE_FULL,
                    queue_depth=depth,
                    error=err.code,
                    error_message=err.message,
                )
                raise err

            state.queue.append(command)
            queue_depth = len(state.queue) + (1 if state.active else 0)
            self._set_status(
                STATUS_QUEUED,
                context,
                dispatch_status=STATUS_QUEUED,
                queue_depth=queue_depth,
                command_age_ms=0,
            )
            if state.worker is None or state.worker.done():
                state.worker = asyncio.create_task(self._worker(transmitter_id))

        try:
            return await command.future
        except asyncio.CancelledError:
            await self._cancel_pending(transmitter_id, command)
            raise

    def shutdown(self) -> None:
        """Stop accepting work and fail pending requests."""
        self._stopped = True
        err = IRLearningHubError(
            ERROR_DISPATCHER_STOPPED,
            "IR command dispatcher was stopped",
        )
        for transmitter_id, state in list(self._states.items()):
            has_active = state.active or state.active_command is not None
            if (
                not has_active
                and state.worker is not None
                and not state.worker.done()
            ):
                state.worker.cancel()
            while state.queue:
                command = state.queue.popleft()
                if not command.future.done():
                    command.future.set_exception(err)
                self._set_status(
                    STATUS_DISPATCHER_STOPPED,
                    command.context,
                    dispatch_status=STATUS_DISPATCHER_STOPPED,
                    queue_depth=0,
                    error=err.code,
                    error_message=err.message,
                )
            if not has_active:
                self._states.pop(transmitter_id, None)

    async def _cancel_pending(
        self,
        transmitter_id: str,
        command: QueuedIRCommand,
    ) -> None:
        """Remove a caller-cancelled command that has not started dispatch."""
        async with self._lock:
            state = self._states.get(transmitter_id)
            if state is None:
                return
            for queued in list(state.queue):
                if queued is command:
                    state.queue.remove(queued)
                    if not command.future.done():
                        command.future.cancel()
                    if not state.queue and not state.active:
                        if state.worker is not None and not state.worker.done():
                            state.worker.cancel()
                        self._states.pop(transmitter_id, None)
                    return

    async def _worker(self, transmitter_id: str) -> None:
        """Drain one transmitter queue."""
        try:
            while True:
                async with self._lock:
                    state = self._states.get(transmitter_id)
                    if state is None or not state.queue:
                        self._states.pop(transmitter_id, None)
                        return
                    command = state.queue.popleft()
                    if command.future.cancelled():
                        continue
                    state.active = True
                    state.active_command = command
                    queue_depth = len(state.queue) + 1

                await self._dispatch_one(command, queue_depth)

                async with self._lock:
                    state = self._states.get(transmitter_id)
                    if state is not None:
                        state.active = False
                        state.active_command = None
        except asyncio.CancelledError:
            raise
        finally:
            async with self._lock:
                state = self._states.get(transmitter_id)
                if (
                    state is not None
                    and not state.queue
                    and not state.active
                    and state.active_command is None
                ):
                    self._states.pop(transmitter_id, None)

    async def _dispatch_one(
        self,
        command: QueuedIRCommand,
        queue_depth: int,
    ) -> None:
        """Dispatch one command if it has not expired."""
        now = time.monotonic()
        age_ms = _elapsed_ms(command.created_monotonic, now)
        if now - command.created_monotonic > self._ttl_seconds:
            err = IRLearningHubError(
                ERROR_COMMAND_EXPIRED,
                "IR command expired before dispatch",
            )
            self._set_status(
                STATUS_EXPIRED,
                command.context,
                dispatch_status=STATUS_EXPIRED,
                queue_depth=queue_depth,
                command_age_ms=age_ms,
                error=err.code,
                error_message=err.message,
            )
            if not command.future.done():
                command.future.set_exception(err)
            return

        queue_wait_ms = age_ms
        self._set_status(
            STATUS_DISPATCHING,
            command.context,
            dispatch_status=STATUS_DISPATCHING,
            queue_depth=queue_depth,
            queue_wait_ms=queue_wait_ms,
            command_age_ms=age_ms,
        )

        try:
            await self._adapter.async_send(command.transmitter, command.code)
        except IRLearningHubError as err:
            self._fail_delivery(command, err, queue_depth)
            return
        except Exception as err:  # pragma: no cover - defensive transport boundary.
            wrapped = IRLearningHubError(
                ERROR_SEND_FAILED,
                f"IR send failed: {err}",
            )
            self._fail_delivery(command, wrapped, queue_depth)
            return

        command_age_ms = _elapsed_ms(command.created_monotonic)
        result = CommandDispatchResult(
            request_id=command.context.request_id,
            status=STATUS_DISPATCHED_UNCONFIRMED,
            delivery_confirmed=False,
            transmitter_id=command.context.transmitter_id,
            queue_wait_ms=queue_wait_ms,
            command_age_ms=command_age_ms,
            queue_depth=queue_depth,
        )
        self._set_status(
            STATUS_DISPATCHED_UNCONFIRMED,
            command.context,
            dispatch_status=STATUS_DISPATCHED_UNCONFIRMED,
            queue_depth=queue_depth,
            queue_wait_ms=queue_wait_ms,
            command_age_ms=command_age_ms,
            delivery_confirmed=False,
        )
        if not command.future.done():
            command.future.set_result(result)
        _LOGGER.debug(
            "IR send dispatched to ZHA (delivery not confirmed): transmitter=%s request_id=%s code_len=%s",
            command.transmitter.get("ieee"),
            command.context.request_id,
            len(command.code),
        )

    def _fail_delivery(
        self,
        command: QueuedIRCommand,
        err: IRLearningHubError,
        queue_depth: int,
    ) -> None:
        """Record a failed ZHA dispatch and fail the caller."""
        self._set_status(
            STATUS_DELIVERY_FAILED,
            command.context,
            dispatch_status=STATUS_DELIVERY_FAILED,
            queue_depth=queue_depth,
            command_age_ms=_elapsed_ms(command.created_monotonic),
            error=ERROR_SEND_FAILED,
            error_message=err.message,
        )
        if not command.future.done():
            if err.code == ERROR_SEND_FAILED:
                command.future.set_exception(err)
            else:
                command.future.set_exception(
                    IRLearningHubError(ERROR_SEND_FAILED, err.message)
                )

    def _set_status(
        self,
        state: str,
        context: CommandContext,
        *,
        dispatch_status: str,
        queue_depth: int,
        queue_wait_ms: int | None = None,
        command_age_ms: int | None = None,
        delivery_confirmed: bool | None = None,
        error: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update hub status with dispatcher metadata."""
        self._status.async_set(
            state,
            action="dispatch",
            location_id=context.location_id,
            ir_device_id=context.ir_device_id,
            command_id=context.command_id,
            error=error,
            error_message=error_message,
            request_id=context.request_id,
            dispatch_status=dispatch_status,
            transmitter_id=context.transmitter_id,
            queue_wait_ms=queue_wait_ms,
            command_age_ms=command_age_ms,
            queue_depth=queue_depth,
            delivery_confirmed=delivery_confirmed,
        )


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _elapsed_ms(start: float, end: float | None = None) -> int:
    return max(0, round(((end if end is not None else time.monotonic()) - start) * 1000))
