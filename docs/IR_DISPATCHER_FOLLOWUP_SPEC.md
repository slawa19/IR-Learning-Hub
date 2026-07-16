# IR Dispatcher Follow-up Spec

## Status

Follow-up after expanded code review of the dispatcher implementation.

## Findings To Address

### F1 - Caller cancellation must not leave stale pending IR commands

If a caller cancels `IRCommandDispatcher.async_send()` while the command is still
waiting in a transmitter queue, the queued command must be removed and must not
be sent later.

Acceptance criteria:

- cancelling a pending `async_send()` task removes that command from the queue;
- the cancelled pending command is never handed to `ZHAAdapter.async_send()`;
- cancellation of a caller waiting for an already active command does not cancel
  the underlying ZHA dispatch.

### F2 - Shutdown must not cancel active ZHA dispatch

The dispatcher spec says commands already handed to Zigbee must not be
cancelled. Shutdown may reject new commands and fail not-yet-started pending
commands, but it must not cancel a worker while it is inside the active
`adapter.async_send()` call.

Acceptance criteria:

- `shutdown()` stops accepting new commands;
- pending queued commands fail with `dispatcher_stopped`;
- active commands already in dispatch are allowed to finish;
- dispatcher tests cover both pending shutdown and active shutdown behavior.

### F3 - Architecture docs must match storage v5

The implementation now uses storage schema version 5 for the narrow
`mute_toggle` migration. Architecture documentation must not still describe the
current schema as v4.

Acceptance criteria:

- `docs/ARCHITECTURE.md` names the current store schema as v5;
- the JSON example uses `"version": 5`.
