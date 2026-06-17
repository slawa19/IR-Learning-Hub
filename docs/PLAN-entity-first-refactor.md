# Plan: Entity-first refactor (expose IR devices to Assist / LLM)

> Goal: turn IR Learning Hub from a **service-first** integration into an
> **entity-first**, canonical Home Assistant integration, so that the user's IR
> devices appear as normal HA entities (`media_player`, `remote`, optionally
> `switch`) that Assist, voice, the LLM API and the UI can control directly —
> **without any extra scripts, automations, helpers, or a custom conversation
> layer**.

This document has two parts:

1. **Prompt review** — what in the original agent prompt is correct, what is
   wrong or risky against current HA canon, and the corrections.
2. **Corrected agent prompt + PR plan** — a ready-to-run prompt and a phased
   PR breakdown designed to land in the minimum number of iterations, plus the
   canonical `command_id` vocabulary and inference rules.

---

## Part 1 — Review of the original prompt

### What is correct and should be kept

- **Core diagnosis is right.** The integration is service-centric and only
  forwards `Platform.SENSOR` (`custom_components/ir_learning_hub/__init__.py:59`).
  The store already holds the right domain model `locations -> devices ->
  commands` (`storage.py`), and `device.type` already exists but is unused as a
  HA domain model (`storage.py:160-165`). Re-projecting that store into entities
  is the correct move.
- **The target platforms are right.** `media_player` and `remote` are the
  canonical domains for IR-driven AV gear, and they are LLM/Assist-exposable.
- **Entity model must come from the store, not YAML** — correct and required.
- **Keep transport (`ZHAAdapter`) and keep existing services for backward
  compatibility** — correct, and reinforced below.
- **Stateless honesty**: `assumed_state`, `RestoreEntity`, optimistic updates,
  no fake hardware polling — all correct and idiomatic for IR.
- **`command_id`, not display name, is the stable semantic layer** — correct,
  and the store already enforces `command_id` to `^[a-z0-9_]+$`
  (`storage.py:25`), so the semantic layer is feasible today.
- **The supplied `command_id` vocabulary and inference rules are good.** They are
  adopted essentially as-is in Part 2.

### ✅ Verified against current docs (entity page updated 2026-05-26)

The prompt's central bet checks out, and the exact API surface was confirmed
against the developer docs. **Use the docs/source for names, not the blog** —
the 2026-03-30 announcement still uses the old/generic `InfraredEntity` name,
but the entity docs page (updated 2026-05-26) defines the real classes:

- Emitter base class: **`InfraredEmitterEntity`** (`device_class = "emitter"`),
  with `async_send_command()` that talks to hardware.
- Receiver base class: **`InfraredReceiverEntity`**.
- Consumer base classes (what `media_player`/`remote`/`switch` build on):
  **`InfraredEmitterConsumerEntity`** and **`InfraredReceiverConsumerEntity`**.
- **Command contract:** *"All IR commands inherit from
  `infrared_protocols.commands.Command` and implement `get_raw_timings()`."*
- **Consumer send helper (exact signature):**
  ```python
  await infrared.async_send_command(hass, emitter_entity_id, command, context=context)
  ```
  Note: it takes an **`entity_id` string**, not a UUID. Ignore any
  `entity_uuid` phrasing from architecture discussions — that is not the
  implementation contract.
- **Consumer integrations send through the emitter, never touching IR hardware
  directly.** Docs: *"Consumer integrations control IR devices by sending
  commands through an emitter entity. They don't interact with IR hardware
  directly."*
- **Manifest:** consumer integrations declare `"dependencies": ["infrared"]`.

### ❗ Corrections — where the original prompt diverges from HA canon

1. **Consumer entities must route through the emitter, not through `ZHAAdapter`.**
   The original prompt (steps 3–4) implies `media_player` / `remote` delegate
   sending to the existing `ZHAAdapter`. That contradicts the platform contract.
   The canonical layering is:

   ```
   media_player / remote / switch  (consumer entities, resolve command_id -> IR code)
        -> infrared platform helper  async_send_command(emitter, code)
             -> InfraredEntity (emitter, our TS1201 wrapper)
                  -> ZHAAdapter  (unchanged transport)
                       -> ZHA / Zosung
   ```

   `ZHAAdapter` is **not** removed — it lives *inside* the emitter entity.
   Transport stays in exactly one place; consumers never import the adapter.

2. **🔴 CONFIRMED — opaque `zosung_base64` is not a canonical IR command.** The
   platform expects an `infrared_protocols.commands.Command` object that
   implements `get_raw_timings()`. Our store treats codes as **opaque
   `zosung_base64`** blobs (`ARCHITECTURE.md:55`) with no raw-timing
   representation. Therefore the "fallback" is **almost certainly the primary
   path for the first release**, not a contingency:
   - Consumer entities still call the emitter through the HA helper / consumer
     base class (canonical), **but** the emitter's send implementation forwards
     the stored opaque code straight to `ZHAAdapter` (transport stays
     encapsulated in the emitter).
   - **Update (spike closed):** the framework never calls `get_raw_timings()` on
     the send path, so a `zosung -> raw` decoder is **not needed** — our emitter
     reads an opaque `code` off a `ZosungCommand(Command)` and forwards it. The
     decoder is purely an optional interop follow-up. See "Spike results".

3. **The store has no change-notification channel.** Step 2 says "prefer
   dispatcher/subscription from store to entity manager" as if it exists. It
   does not — every `storage.py` mutator just calls `async_save()`. The refactor
   must **add** a dispatcher signal emitted after each mutation. There is a local
   precedent to mirror: `HubStatus.async_subscribe` (used by `sensor.py:56`).

4. **Virtual devices must become real HA *devices*, not just entities.** The
   prompt says "device info" in passing but the agent must explicitly map each
   registry device to a `device_registry` entry via `DeviceInfo` with stable
   `identifiers = {(DOMAIN, f"{location_id}__{ir_device_id}")}`. Entity
   `unique_id` should be `f"{location_id}__{ir_device_id}"` (plus a suffix for
   `switch`). This is what makes the device cleanly exposable to Assist as a unit.

5. **Config-entry ownership of virtual entities is undefined — and unload is the
   sharp edge.** This is a *hub* integration with **one config entry per
   transmitter**, and `hass.data[DOMAIN]` is a shared singleton across entries
   (`__init__.py:142-159`). If every entry forwards the consumer platforms,
   virtual entities get created N times. Pick a single owner (recommendation:
   the first/primary entry owns the registry-derived consumer entities; every
   transmitter entry owns only its own emitter entity). **But "primary owns it"
   is incomplete without unload handling:** when the primary entry is unloaded
   while secondary transmitter entries remain, the consumer entities must not be
   orphaned or silently duplicated. Define explicit behavior: on primary unload,
   either (a) re-elect a new owner among remaining entries and reload the
   consumer platforms onto it, or (b) tear the consumer entities down cleanly
   before unload completes. The agent must implement and test this transition.

6. **Virtual devices have no transmitter association.** `resolve_transmitter`
   requires a single enabled transmitter or an explicit id
   (`storage.py:101-124`). With >1 transmitter, a virtual device must know which
   emitter to use. Add an optional `transmitter_id` to the device model (soft
   migration) and fall back to the existing single-transmitter resolution. In
   `DeviceInfo`, set **`via_device`** to the chosen transmitter's HA device when
   `transmitter_id` is set — this is the canonical HA device graph ("virtual IR
   device goes *through* the TS1201 emitter").

7. **Storage migration is required and currently absent.** `STORAGE_VERSION = 1`
   and `Store` is created bare as `Store(hass, STORAGE_VERSION, STORAGE_KEY)`
   with no migration (`storage.py:24,50`). Bump to **version 2** and implement
   migration via the **`_async_migrate_func` override** on the `Store` (or the
   equivalent current-core mechanism) — **not** via a non-existent
   `async_migrate_func` constructor parameter. Migration must be additive/soft:
   add `preferred_domain`/`transmitter_id`/optional `capabilities`, and never
   rewrite or drop existing `locations`/`commands`/`transmitters`.

8. **New device fields need a write path in the service API, not just the store.**
   `add_device` currently accepts only `type` (`__init__.py:111`,
   `DEVICE_SCHEMA` at `__init__.py:126-131`). Extend the `add_device` schema
   (and add an `update_device` service if needed) so `preferred_domain` and
   `transmitter_id` can actually be set; otherwise the new fields have no
   user-facing path and stay default-only.

9. **The runtime manager must not add entities across platforms from one place.**
   In HA, `async_add_entities` is **per-platform**: `media_player.py` adds media
   players via its own `async_setup_entry` callback, `remote.py` adds remotes,
   `switch.py` adds switches. A single `entity_manager` that calls every
   platform's add-callback is an anti-pattern. Make the shared module a
   **registry/capability *diff* helper** (decides what should exist per device
   and emits per-platform "add these / remove these" sets); keep the actual
   `async_add_entities` call inside each platform module, fed by the dispatcher
   signal.

10. **`infrared` dependency.** `manifest.json` currently has
    `"dependencies": ["zha"]`. Add `"infrared"` → `"dependencies": ["zha",
    "infrared"]` (docs show consumer integrations declaring it in
    `dependencies`).

### Net assessment

The original prompt is **directionally correct and well-scoped**, but as written
it would cost extra iterations because of (a) the wrong consumer→transport
layering, (b) a now-**confirmed** command-model mismatch (opaque `zosung_base64`
vs. `Command.get_raw_timings()`) that makes the internal-forward path the v1
default, and (c) several missing foundations (store dispatcher, device-registry
mapping with `via_device`, `_async_migrate_func` migration, per-platform entity
adds, unload/owner re-election, and a service write path for the new fields).
The corrected prompt below front-loads a tiny verification spike and a
foundation PR so the entity PRs land cleanly.

---

## Part 2 — Corrected agent prompt

> Paste the following to the implementing agent.

You are working in the `slawa19/IR-Learning-Hub` repository. Refactor the
integration so it **canonically exposes top-level Home Assistant entities** for
IR devices and makes them directly controllable by Assist / voice / the LLM API
/ the UI, **without requiring any extra scripts, automations, or helper
entities**.

**Architecture priority order (use this to break ties):**
1. Canonical HA entities.
2. Backward compatibility of existing `ir_learning_hub.*` services.
3. Minimal changes to the transport layer (`ZHAAdapter`).

**Hard constraints:**
- Do not remove or rewrite the ZHA transport in `zha_adapter.py`.
- Do not replace working services with scripts/automations/helpers.
- Do not build the UX around raw service calls.
- Do not build entity semantics from display labels — use `command_id`.
- Do not hardcode the user's Denon/Sony devices as special cases; the solution
  must be general (capability inference from `command_id`).
- Do not store business state in `input_boolean`/`input_select`.
- Do not build a custom conversation layer instead of real entities.

**Mandatory canonical layering (this corrects a common mistake):**
Consumer entities (`media_player`/`remote`/`switch`) must send IR **through the
emitter entity** (via `infrared.async_send_command(hass, emitter_entity_id,
command, context=context)` or an `InfraredEmitterConsumerEntity` base class),
**never** by calling `ZHAAdapter` directly. `ZHAAdapter` lives *inside* the
emitter entity.

```
media_player / remote / switch   (resolve command_id -> stored IR code)
  -> infrared.async_send_command(hass, emitter_entity_id, command, context=...)
       -> InfraredEmitterEntity (wraps ZHAAdapter, represents the TS1201)
            -> ZHAAdapter (unchanged)
                 -> ZHA / Zosung
```

Use the exact class/helper names from current docs (entity page updated
2026-05-26), **not** the blog: `InfraredEmitterEntity`,
`InfraredReceiverEntity`, `InfraredEmitterConsumerEntity`,
`InfraredReceiverConsumerEntity`. The helper takes an **`entity_id` string**,
not a UUID. IR commands inherit `infrared_protocols.commands.Command` and
implement `get_raw_timings()`.

### Step 0 — Verification spike (do this first, ~30 min, blocking)

Already confirmed from docs (do not re-litigate): class names above; the helper
signature `infrared.async_send_command(hass, emitter_entity_id, command,
context=context)`; commands inherit `infrared_protocols.commands.Command` and
implement `get_raw_timings()`; consumer integrations declare
`"dependencies": ["infrared"]`. Because our codes are **opaque `zosung_base64`**
with no raw-timing form, the decoded-signal path is **the expected v1 reality**.

The spike only needs to determine, against current core source:
- whether you can wrap our opaque code in a `Command` subclass that the helper
  accepts (e.g. one whose `get_raw_timings()` is unavailable/raises) and still
  drive our emitter, **or** whether the consumer should bypass the helper and
  call an emitter method directly while still going through the emitter entity;
- the precise `InfraredEmitterConsumerEntity` constructor/wiring (how a consumer
  binds to a specific emitter `entity_id`).

Record findings under "Spike results" below.

> **These two residual items are prerequisites for PR2, NOT PR1.** Home
> Assistant is not installed in this environment (no `homeassistant` /
> `infrared_protocols` packages on disk), so do not search the filesystem for
> them. The contracts already captured in "Spike results" from the docs are
> enough to start. Confirm the two items against real source at the **start of
> PR2** (install HA into a venv, or read `home-assistant/core`'s
> `homeassistant/components/infrared/` on GitHub). **PR1 does not depend on any
> `infrared` platform detail — proceed to it directly.**

**Decision gate (default = path B for v1):**
- **Path A (fully canonical):** only if a `zosung_base64 -> raw timings` decoder
  is in scope — emit real `get_raw_timings()` and route through the helper.
- **Path B (default for first release):** consumer entities still call **through
  the emitter entity** (helper or consumer base class), but the emitter's send
  implementation forwards the stored opaque code to `ZHAAdapter` internally.
  Consumers never import the adapter. Document this limitation and file the
  `zosung -> raw` decoder as a follow-up toward a fully standards-compliant
  emitter.

### Step 1 — Storage foundation (no entities yet)

- Bump `STORAGE_VERSION` to `2`; implement a **soft, additive** migration by
  overriding **`_async_migrate_func`** on the `Store` subclass (the current code
  uses a bare `Store(hass, STORAGE_VERSION, STORAGE_KEY)` with no migration —
  do **not** pass a non-existent `async_migrate_func` constructor arg). Never
  drop existing `locations`/`commands`/`transmitters`.
- Add optional device fields, all backward-compatible:
  - `preferred_domain`: `media_player` | `remote` | `switch` | `auto`
    (default `auto`, derived from `type` + capabilities).
  - `transmitter_id`: optional; which emitter sends for this device.
- **Add a write path for the new fields:** extend the `add_device` service schema
  (`__init__.py` `DEVICE_SCHEMA`) and add an `update_device` service so
  `preferred_domain` and `transmitter_id` can be set by users/UI — not just
  defaulted.
- Add a **change-notification dispatcher**: after every store mutation, emit
  `async_dispatcher_send(hass, f"{DOMAIN}_registry_updated")`. Mirror the
  existing `HubStatus.async_subscribe` pattern (`status.py`, used by
  `sensor.py`). Do not use polling.
- Add a `capabilities.py` module: pure functions that infer capabilities from a
  device's set of `command_id`s, plus a `command_id` **alias normalization map**
  (see vocabulary below). No HA imports in this module so it is trivially
  unit-testable.

### Step 2 — Infrared emitter platform

- Add `Platform.INFRARED`; create `infrared.py` with one `InfraredEmitterEntity`
  per configured transmitter, wrapping `ZHAAdapter` (do not duplicate transport).
- Set `manifest.json` to `"dependencies": ["zha", "infrared"]`.
- The emitter represents the **TS1201 hardware**, not Denon/Sony.
- `unique_id` = the transmitter id (normalized IEEE); attach to the transmitter's
  HA device. Every transmitter entry owns **only** its own emitter entity.

### Step 3 — Consumer entity layer + diff helper

- Create a shared **`registry_runtime.py` diff helper** (not a cross-platform
  adder): given the current store, it computes, per device, which consumer
  entities should exist (domain + unique_id + capabilities) and emits per-domain
  add/remove sets. **It must not call `async_add_entities` for other platforms.**
- Each platform module owns its own additions: `media_player.py`, `remote.py`,
  and (if clean) `switch.py` each register their `async_setup_entry`
  `async_add_entities` callback, subscribe to `{DOMAIN}_registry_updated`, and
  add/remove **their own** entities dynamically on device/command changes.
- **Ownership + unload:** the consumer entities are owned by a single (primary)
  config entry; every transmitter entry owns its emitter. On primary-entry
  unload while other entries remain, either re-elect a new owner and reload the
  consumer platforms, or tear consumer entities down cleanly first — never leave
  orphans or duplicates. Implement and test this transition.
- Map each registry device to a HA **device** via `DeviceInfo`
  (`identifiers = {(DOMAIN, f"{location_id}__{ir_device_id}")}`, and
  `via_device` = the resolved transmitter's HA device when `transmitter_id` is
  set); entity `unique_id = f"{location_id}__{ir_device_id}"`.
- Domain selection from `device.type` / `preferred_domain`:
  - `media_player` → `MediaPlayerEntity`
  - `remote` / `generic` → `RemoteEntity`
  - `switch` → `SwitchEntity` (only if capabilities are pure on/off)

### Step 4 — Command mapping & capabilities (from `command_id`)

- `MediaPlayerEntity`: resolve features from inferred capabilities and map HA
  service calls to `command_id`s (power/play/pause/stop/next/previous/volume/
  mute/source). Build `source_list` from `source_*` commands; implement
  `async_select_source`. Resolve commands by `command_id`, never by name.
- `RemoteEntity`: `turn_on`/`turn_off`/`toggle` send the corresponding stored
  power commands if present; `async_send_command([...])` resolves each item
  strictly by `command_id` and raises **`HomeAssistantError`** with a clear
  message if a `command_id` is missing (no silent display-name fallback).
- `SwitchEntity`: on/off via `power_on`/`power_off` or `power_toggle`.

### Step 5 — Honest state model

- `assumed_state = True` when there is no feedback channel.
- Use `RestoreEntity` to restore last assumed state across restarts.
- Update state **optimistically** after a successful send.
- Power semantics: real on/off only when both `power_on` and `power_off` exist;
  with only `power_toggle`, force `assumed_state` and do not promise true on/off;
  with no power command, do not advertise power.
- **`MediaPlayerEntity` must not advertise an OFF state it cannot deliver.** If
  there is no reliable `power_on`, do not promise real off/on semantics — for
  toggle-only devices prefer `ON`/`IDLE` with `assumed_state = True` rather than
  a fake `OFF` state. Only model true `OFF` when `power_off` (and a reliable
  way back on) exists.
- No fake hardware polling.

### Step 6 — Assist exposure (no scripts)

- Human-friendly entity names, `DeviceInfo`, `supported_features`, and
  `source_list`. Entities register normally so they are directly exposable to
  Assist. Do not add a bespoke conversation layer.
- **Dynamic lifecycle:** entities for devices added/removed at runtime must
  appear/disappear automatically via the `entity_manager` dispatcher
  subscription (Step 3) — no restart, no scripts. New entities must register
  with a stable `unique_id` and `DeviceInfo` so they are immediately *eligible*
  for Assist exposure.
- **Exposure is HA-owned and opt-in — do NOT force it.** In current HA, creating
  an entity does not auto-expose it to Assist/LLM; exposure is governed by
  Settings → Voice assistants → Expose (including the per-assistant
  "expose new entities automatically" toggle). The integration must not call
  `async_expose_entity` or otherwise override the user's exposure policy — that
  is against HA canon (HA made exposure opt-in deliberately, for parser
  performance and LLM context cost). Our responsibility ends at making entities
  correctly registered and exposable; turning on auto-exposure is a one-time HA
  setting (not a script/automation), and it should be documented in the README
  rather than coded around.

### Step 7 — Backward compatibility

- All existing `ir_learning_hub.*` services keep working unchanged.
- The new entity layer uses the **same** store and the **same** transport.
- Keep `Platform.SENSOR` (status sensor) working.

### Step 8 — Tests (required)

- Capability inference from `command_id` sets (table-driven).
- `command_id` alias normalization.
- Entity materialization from a seeded store; dynamic add/remove on dispatcher
  signal.
- `MediaPlayerEntity` calls the correct `command_id` for
  play/pause/stop/volume/mute/source-select.
- `RemoteEntity` `turn_on`/`turn_off`/`toggle` and `send_command` resolution +
  clear error on missing `command_id`.
- Optimistic/assumed-state transitions and `RestoreEntity` restore.
- Services still resolve and send after the refactor.
- Storage v1→v2 migration preserves existing data.

### Step 9 — Deliverable (PR description)

Include: the new architecture summary; new platforms; `command_id -> HA feature`
mapping; remaining stateless-IR limitations; full list of changed/added files;
and the Spike results + which routing path (helper vs internal-forward) was used.

---

## Canonical `command_id` vocabulary

`command_id` is the **stable semantic key** for code and entities. `name` is a
human label only. Inference and mapping operate on `command_id` exclusively.
Naming rules: lowercase, `_`-separated, no brands except sources/vendor modes,
action semantics over button labels.

**Power:** `power_on`, `power_off`, `power_toggle`
**Playback:** `play`, `pause`, `play_pause_toggle`, `stop`, `next`, `previous`,
`fast_forward`, `rewind`, `eject`
**Volume:** `volume_up`, `volume_down`, `mute`, `unmute`, `mute_toggle`
**Navigation:** `up`, `down`, `left`, `right`, `select`, `back`, `home`, `menu`,
`info`, `exit`
**Digits:** `digit_0` … `digit_9`
**Tuner/channels:** `channel_up`, `channel_down`, `last_channel`, `guide`
**Sources (`source_*`):** `source_tv`, `source_pc`, `source_cd`, `source_dvd`,
`source_bd`, `source_aux`, `source_usb`, `source_bluetooth`, `source_tuner`,
`source_phono`, `source_tape`, `source_video_1..3`, `source_hdmi_1..3`,
`source_denon`, `source_ugreen`, `source_home_ass`
**Receiver/player extras:** `surround_mode`, `sound_mode`, `pure_direct`,
`sleep`, `display`, `subtitle`, `audio_track`
**Climate-like (future):** `mode_cool/heat/dry/fan/auto`,
`fan_low/medium/high/auto`, `temp_up`, `temp_down`, `swing_toggle`

### Alias normalization map (backward compat for older ids)

`vol_up → volume_up`, `vol_down → volume_down`, `power → power_toggle`,
`forward → fast_forward`, `backward → rewind`, `ok → select`, `return → back`,
`input_tv → source_tv`, `input_pc → source_pc` (extend per `source_*`).
Avoid `open`/`close`/`forward`/`backward` as canonical ids; normalize them.

### Inference rules

- **Media features:** add `play` if `play`; `pause` if `pause` or
  `play_pause_toggle`; `stop` if `stop`; next/previous if present; volume step
  semantics if `volume_up`/`volume_down`; mute if `mute`/`mute_toggle`; build
  `source_list` from any `source_*`.
- **Power semantics:** `power_on`+`power_off` → real on/off; only
  `power_toggle` → `assumed_state = True`; none → no power feature.
- **Sources:** map each `source_*` to a display name via a predictable formatter
  (`source_video_1 → "Video 1"`, `source_pc → "PC"`, `source_home_ass →
  "Home Ass"`); the canonical id stays `source_*`. An optional display label may
  be stored, but the id remains the key.
- **Remote:** `send_command([...])` resolves strictly by `command_id`; missing
  id → `HomeAssistantError` with a clear message (no silent fallback).

### Minimum set for the Denon/Sony case (validation target)

`power_toggle` or (`power_on`+`power_off`), `play`, `pause`, `stop`,
`volume_up`, `volume_down`, `mute`, `source_tuner`, `source_video_1`,
`source_video_3`, `source_tape`, `source_pc`, `source_denon`, `source_ugreen`,
`source_home_ass`.

---

## PR plan (minimum iterations)

Designed so each PR is independently reviewable/mergeable and the risky unknown
is resolved first. PRs 1–3 can be squashed into one branch if the maintainer
prefers a single review.

**Progress:** PR0 ✅ closed (see "Spike results"). PR1 ✅ merged. PR2 ✅ reviewed
& accepted on `feat/entity-first-pr0-pr1` — `ir_command.py` (`ZosungCommand`),
`infrared.py` (one emitter per entry; DeviceInfo child-model
`identifiers={(DOMAIN, transmitter_id)}` + `via_device=("zha", ieee)`),
`PLATFORMS = [Platform.SENSOR, Platform.INFRARED]`, manifest `["zha","infrared"]`.
`ZosungCommand` verified against installed `infrared-protocols==6.0.1` (27 tests
in `.venv314`). PR3a (remote consumer spine) + fix-pass done. **Smoke re-run
2026-06-16: device graph ✅ and lifecycle ✅ fixed/verified; the remaining
"toggle/missing-command 500" is a REST-transport artifact, not a code bug —
`ServiceValidationError` is correct (see "PR3a smoke-test findings"). Spine
effectively confirmed; two cheap WS/UI verifications + manual Scenario B remain
before PR3b.**

| PR | Title | Scope | Tests |
|----|-------|-------|-------|
| **PR0 (spike)** ✅ | Infrared platform fit | Step 0 verification; results + chosen routing path recorded below. | n/a |
| **PR1** ✅ | Storage foundation | Step 1: store v2 migration via `_async_migrate_func`, `preferred_domain`/`transmitter_id` fields + `add_device`/`update_device` write path, `{DOMAIN}_registry_updated` dispatcher, `capabilities.py` (inference + alias map). No new entities. | Migration v1→v2; capability inference; alias normalization; new fields persisted via service. |
| **PR2** ✅ | Infrared emitter platform | Step 2: `Platform.INFRARED`, `infrared.py` `InfraredEmitterEntity` wrapping `ZHAAdapter`, `ZosungCommand(Command)`, manifest `["zha","infrared"]`. | Emitter send forwards to adapter; one emitter per transmitter; `ZosungCommand` carries opaque code. |
| **PR3a** ✅ | Consumer spine (remote) | `registry_runtime.py` diff helper + `remote.py`; DeviceInfo + `via_device`; single-owner config entry + lifecycle (F1–F4 fixed via `async_remove_entry`); dynamic add/remove; RestoreEntity + assumed/optimistic; `ServiceValidationError`. Verified on real HA (1-transmitter). | Materialization; dynamic add/remove; command_id mapping; send + `ServiceValidationError`; lifecycle/cleanup; owner-removal re-election (unit). |
| **PR3b** 🟡 | Consumer domains (media_player + switch) | `media_player.py` + `switch.py` on a shared consumer base extracted from `remote.py`; honest off-semantics; cross-domain transition. Code works on real HA; capability detection fixed by PR3c. | Off-semantics; optimistic+Restore; cross-domain move; existing tests green. |
| **PR3c** ✅ | Explicit command `feature` semantics | Replace "infer capability from `command_id` text" with an explicit per-command `feature` role. Includes stale-transmitter prune on entry removal and `ServiceValidationError` wrapping for transmitter resolution. | feature-based inference; v3 migration seeder; select_source by label; remote raw passthrough; existing tests green. |
| **PR3d** ⬜ | Canonical transmitter identity + reconcile fixes | Real-HA PR3c smoke surfaced an identity desync + a dropped-reconcile race — see "PR3d". Blocks the PR3b/PR3c smoke. | ref resolver; reconcile orphans; write-path validation; no masking fallback; v3→v4 migration; trailing-edge reconcile; transmitters in `list_commands`. |
| **PR-MT** ⬜ | Multi-transmitter support | **After PR3d.** Remaining: per-device transmitter selector UI, ownership decoupling — see "Multi-transmitter PR". | Ownership decoupling; lifecycle edges closed. |
| **PR4** | Docs + back-compat hardening | Update `ARCHITECTURE.md`, `SERVICES.md`, `README.md` (incl. Assist "expose new entities" note), `ROADMAP.md`; back-compat service tests; final PR-description deliverable. | Services still resolve/send post-refactor. |

### File map (added / changed)

- **Added:** `infrared.py`, `media_player.py`, `remote.py`, (optional)
  `switch.py`, `registry_runtime.py` (diff helper — not a cross-platform adder),
  `capabilities.py`.
- **Changed:** `__init__.py` (extend `PLATFORMS`, single-owner forwarding +
  unload/owner re-election, wire dispatcher), `storage.py` (v2
  `_async_migrate_func` + fields + dispatcher emits), `__init__.py` service
  schemas (`add_device`/`update_device` for new fields), `manifest.json`
  (`infrared` dependency), `const.py` (new signal/field constants), docs.

### PR3b implementation note (2026-06-17) — awaiting real-HA smoke

Implemented locally:
- `consumer.py` shared send path, transmitter/emitter resolution, registry
  cleanup, common `ConsumerEntityManager`, and consumer entity DeviceInfo mixin.
- `remote.py` now uses the shared consumer base; behavior covered by existing
  remote tests.
- `media_player.py` implements `MediaPlayerEntity` with capability-derived
  features, `source_list`/`async_select_source`, optimistic state, RestoreEntity,
  and honest power semantics (`explicit`, `toggle`, `none`).
- `switch.py` implements pure on/off devices only, with assumed optimistic state.
- `CONSUMER_PLATFORMS = [remote, media_player, switch]`; owner-only forwarding
  and re-election lifecycle unchanged.

Local verification: `.venv314` full pytest run passed (65 tests + 13 subtests);
unittest discovery passed (30 tests in `.venv314`, 28 tests / 3 skipped in the
base interpreter).

Real-HA smoke checklist for PR3b:
- Set a real device (for example the Sony receiver) to
  `preferred_domain: media_player`; verify a `media_player.*` entity appears
  without duplicate/orphan `remote.*`.
- Verify features match learned command IDs: play/pause/stop/next/previous,
  volume step, mute, source select, and power according to `power_mode`.
- Send harmless real IR codes through play/pause/stop/volume/mute/source and
  confirm they go through the infrared emitter.
- Verify `async_select_source` updates the optimistic source and sends the
  stored command whose `feature` is `source` and whose `name` matches the
  selected source label.
- Verify `power_mode=none` does not expose turn_on/turn_off; `toggle` is assumed
  and optimistic; `explicit` reaches true OFF.
- Switch a pure power device to `preferred_domain: switch`; verify on/off/toggle
  and lifecycle cleanup.
- Test error paths through WS/UI or Developer Tools, not REST.
- **Unchanged transport:** `zha_adapter.py`, `ir_formats/*`, `device_profiles.py`
  (extend profiles only if Step 0 requires a decoder).

### PR3a smoke-test findings (2026-06-16, HA 2026.6.3, real TS1201) — must fix before PR3b

Passed: integration loads; emitter entity exists (`infrared.ir_transmitter_…`,
device_class emitter); consumer remotes materialize from registry
(`remote.denon_cd`, `remote.sony_str_db840_receiver`); `add_device`/`save_command`
create `remote.*` live; `remote.send_command` on a real code returns OK.

**Bugs (all reproduced):**
1. **Device graph broken — `via_device` not linked.** Emitter shows
   `via_device=null` (not under ZHA TS1201); consumer `remote.*` show
   `via_device=null` (not under emitter). Root cause: emitter & remote platforms
   are forwarded by the same owner entry with no guaranteed order, so the emitter
   device often doesn't exist when a remote sets `via_device`. Fix: **explicitly
   register the transmitter device in `__init__.async_setup_entry`**
   (`dr.async_get_or_create(identifiers={(DOMAIN, transmitter_id)},
   via_device=("zha", ieee), …)`) before forwarding platforms; entities then just
   attach by identifier. Also re-measure with `via_device_id` (not `via_device`)
   and re-confirm the IEEE colon-form matches ZHA.
2. **`remote.toggle` → HTTP 500** (and missing-command → HTTP 500). Root cause:
   user-facing failures raise plain `HomeAssistantError`, which the REST API
   surfaces as 500 + traceback. Fix: raise **`ServiceValidationError`**
   (`homeassistant.exceptions`) for "no command_id" and "no supported power
   command". Grab the real traceback from the HA log first to rule out a second
   crash.
3. **Missing-command not a readable domain error** — same root cause/fix as #2.
4. **Lifecycle orphan.** After `delete_device`/`delete_location`, `remote.*`
   stays in the state machine as `unavailable`/`restored=true`. Root cause:
   `entity.async_remove()` does not delete the **entity registry** entry; a
   registry-backed entity is restored as unavailable. Fix: on reconcile-remove,
   `entity_registry.async_remove(entity_id)` **and** clean up the now-empty
   virtual device from the device registry. Reproduced on two devices
   (`smoke_test_tv`, `test`) — systemic, not a fluke.

**Fix-pass result (smoke re-run 2026-06-16):** Bug 1 ✅ device graph correct
(verified via `via_device_id`: emitter → ZHA TS1201; remotes → emitter; also
confirmed on fresh device `Test1`). Bug 4 ✅ lifecycle cleanup works (entity 404
+ device removed; confirmed on `smoke_test_tv` and `Test1`). Bugs 2 & 3 still
showed HTTP 500 over REST — **resolved as NOT a code bug:**

- HA's REST endpoint `POST /api/services/{domain}/{service}` converts **only**
  `vol.Invalid` and `ServiceNotFound` to HTTP 400; `ServiceValidationError` and
  any `HomeAssistantError` propagate to **HTTP 500 by design** (verified against
  `home-assistant/core` `components/api/__init__.py`). This is identical for all
  HA integrations.
- Our code correctly raises `ServiceValidationError` (no pre-validation crash).
  Over WS / Developer Tools / Assist / voice / LLM / automations it surfaces as a
  clean, translatable error — **not** a 500. The 500 is a REST-transport artifact
  of the openclaw test client only. Do **not** contort the code (e.g. raise
  `vol.Invalid`) to satisfy REST.
- **Test-design flaw:** `smoke_test_tv` had only `mute` (no power command), so
  `remote.toggle` *correctly* errors ("no supported power command"). To verify
  optimistic toggle, the test device must have `power_toggle` (or
  `power_on`+`power_off`).

Cheap verification (no full smoke cycle, use WS/UI not REST):
1. Add a test device with `power_toggle`; `remote.toggle` → success + optimistic
   `off↔on` flip.
2. Call a missing command via Developer Tools → Actions (UI) or WS → readable
   "has no command_id …" message, integration stays up. Or check
   `home-assistant.log`: a clean `ServiceValidationError` line **without**
   traceback = correct; an unexpected traceback = real bug.

Optional polish (not a blocker): give the `ServiceValidationError`s a
`translation_domain`/`translation_key` so the message localizes in the UI/Assist.

**Second re-run (2026-06-16, rerun #2):** A ✅ happy-path `remote.toggle` flips
`off↔on` with a `power_toggle` command, no 500. B ✅ accepted (no crash; correct
by design). C ✅ lifecycle re-confirmed.

**Scenario B (multi-entry) — partially verified on live HA:**
- ✅ **Single-owner confirmed:** adding a second config entry (Manual setup, fake
  IEEE `…00:99`) produced a second emitter but did **not** duplicate the consumer
  entities (`remote.denon_cd`/`remote.sony_str_db840_receiver` stayed single).
- ✅ **Non-owner unload confirmed:** deleting the second/fake (non-owner) entry
  removed the fake emitter cleanly; both consumer remotes survived single, no
  dupes, no `unavailable`/`restored` orphans.
- ❗ **Owner re-election NOT verified on live HA** (operator declined to delete the
  real owner — reasonable; would disturb production). Note: `async_unload_entry`
  already uses `async_schedule_reload(new_owner_id)` (good).

**Code-review of the re-election branch (2026-06-16) — latent multi-entry bugs
(do NOT claim multi-transmitter support until fixed; single-transmitter installs
are unaffected):**
- **F1 — infinite reload loop with 3+ entries.** `_remove_entry_and_select_new_owner`
  runs inside `async_unload_entry`, which also fires on reloads. It can't tell a
  reload from a removal, so each scheduled reload of the newly-elected owner
  re-elects another entry and schedules yet another reload → ping-pong forever.
  (1–2 entries terminate; 3+ loop.)
- **F2 — asymmetric platform unload.** After re-election the new owner is reloaded
  with `_entry_platforms()` now including `REMOTE`, but `REMOTE` was never set up
  on that entry → `async_unload_platforms` is asked to unload a never-loaded
  platform (relies on HA tolerating it; unverified, could fail the reload).
- **F3 — heavy teardown on 2-entry re-election.** Reloading the last remaining
  (newly-elected) owner hits the empty-`entries` branch → `hass.data.pop(DOMAIN)`
  + services removed + learn tasks cancelled, then setup rebuilds from the
  persisted store. Recovers, but heavy/transient.
- **F4 — dead-but-destructive set branch** (`__init__.py` ~271–273): if `entries`
  were ever a `set`, it resets all entries to `{}`. Unreachable today (always a
  dict) but a latent mine.
- **Recommended fix:** separate reload from removal — `async_unload_entry` only
  unloads platforms; implement `async_remove_entry(hass, entry)` to pop the entry,
  re-elect the owner, `async_schedule_reload(new_owner)`, and do final teardown
  when no entries remain. This makes reloads ownership-stable and removes F1–F3.
- **Data safety confirmed:** registry is a single persisted store independent of
  entries — deleting any/all entries never wipes devices/commands.

**Lifecycle fix applied & reviewed (2026-06-17) — F1–F4 RESOLVED.** Implemented
exactly as recommended: `async_setup_entry` records the actual forwarded
platforms per entry in `domain_data["forwarded"]`; `async_unload_entry` only
unloads `forwarded[entry_id]` (no
re-election/teardown — fixes F2/F3); new `async_remove_entry` does pop +
re-election + `async_schedule_reload(new_owner)` or `_teardown_domain` when empty
(fixes F1); dead set-branch removed (F4). Verified by trace across all scenarios
(1 reload / 2-entry owner removal / 3+ no loop / non-owner / last entry) and unit
tests (45 passed). `REGISTERED_SERVICES` complete (19 incl. `update_device`).

Residual multi-transmitter-only edges (documented, not blockers; single-
transmitter installs unaffected). **Decision (2026-06-17): do NOT fix now.**
- **Disable (not remove) of the owner entry** doesn't re-elect (HA only calls
  `async_unload_entry` on disable), so consumer entities stay down until
  re-enable. A "proper" fix would re-detect disable-vs-reload in unload — exactly
  the complexity removed to kill F1 (reload-loop) — so a point fix is a net
  negative.
- **Removing the owner entry purges consumer-entity registry customizations**
  (area/rename/expose); re-election recreates them fresh (unique_id stable).
- **Both share one root cause: consumer entities/devices are owned by a
  transmitter config entry.** Do NOT patch them separately. When multi-transmitter
  is actually committed, the single correct fix is to **decouple consumer-entity
  ownership from any transmitter entry** (e.g. a stable hub owner independent of
  hardware). That dissolves both edges at once and avoids re-introducing
  disable/reload discrimination. Until then: keep as documented limitations,
  optionally mark multi-transmitter as experimental in user docs.

**Verdict: PR3a spine + lifecycle fix confirmed → ready for PR3b.**
Known multi-transmitter limitations are the documented owner-disable and
registry-customization edge cases above; single-transmitter installs are
unaffected.

### PR3b smoke-test findings (2026-06-17, real HA + real Sony receiver)

- ✅ **Domain transition works** (remote→media_player via `update_device` with the
  real `ir_device_id`, not the entity_id tail). No dupes.
- 🔴 **Capability detection is wrong for real data.** `supported_features=1416`
  = VOLUME_STEP|VOLUME_MUTE|TURN_ON|TURN_OFF only; **no PLAY/PAUSE/STOP/
  SELECT_SOURCE and empty `source_list`**, even though the device has those
  commands. Root cause: inference reads canonical `command_id` text, but the
  registry's real ids are arbitrary (`tuner`, `cd`, `video_1`, … — no `source_`
  prefix; play/pause/stop named differently too). → fixed by PR3c.
- ✅ **Send crashed with `transmitter_required`/500.** A device with
  `transmitter_id=null` + a **stale transmitter** still in the store (the fake
  `00:00…99` from the Scenario B test — its config entry was removed but the
  store record was never pruned) → `resolve_transmitter(None)` sees >1 → raises
  `IRLearningHubError` (raw 500 over REST). → fixed by PR3c bundle (prune store
  transmitter on entry removal + wrap as `ServiceValidationError`).

### PR3c — explicit command `feature` semantics

**Refines a Part-1 assumption:** "`command_id` is the stable semantic layer" is
wrong — `command_id` is a user-authored arbitrary **identity**, so inferring
capabilities from its text never generalizes. Canonical HA practice is to
**declare capabilities explicitly.** Introduce a per-command semantic role.

- **Model:** add optional `feature` to each command — a closed enum:
  `power_on|power_off|power_toggle|play|pause|play_pause_toggle|stop|next|`
  `previous|fast_forward|rewind|volume_up|volume_down|mute|unmute|mute_toggle|`
  `source`. Sources collapse to `feature: source`; the command's `name` is its
  `source_list` label (no `source_*` ids needed). Additive — no data loss.
- **Migration (seed once):** pre-fill `feature` where `command_id` matches a
  canonical token/alias; leave unset otherwise. The old vocabulary/alias map
  moves here (seeder) + UI suggestions — **not** runtime inference.
- **Inference (`capabilities.py`):** read **only** `feature` at runtime
  (naming-independent, trivial).
- **Write path:** `add/save/update_command` accept `feature` (validated);
  Lovelace card gets a role selector + source label.
- **`registry_runtime`/EntitySpec:** `command_keys` becomes `feature →
  stored_command_id`; sources = `(command_id, label)` list where
  `feature == source`.
- **Consumers:** `media_player`/`switch` resolve by `feature`; `remote.send_command`
  stays **raw passthrough by literal `command_id`** (the generic escape hatch).
- **Tests:** feature-based inference; migration seeder (canonical → seeded,
  arbitrary → unset); `select_source` by label; remote raw passthrough; existing
  tests green.

This makes the entity layer universal (any naming) and canonical (explicit
capability declaration). After PR3c, re-run the PR3b smoke.

**Implemented 2026-06-17.** Storage is v3; commands have optional `feature`;
v3 migration seeds only recognized legacy ids/aliases and leaves arbitrary ids
unset; runtime inference reads only `feature`; `remote.send_command` is raw
literal `command_id` passthrough; media_player/switch resolve by feature;
sources use `feature: source` with command `name` as the label; services and the
Lovelace card expose a role selector; stale transmitter records are pruned on
entry removal and transmitter resolution errors are wrapped as
`ServiceValidationError`.

### PR3d — canonical transmitter identity fix

Real-HA PR3c smoke (2026-06-17) still crashed `media_player.volume_up` with
`More than one transmitter is enabled` / `Transmitter ir_transmitter_… is not
available`. Code review found a **transmitter identity desync** — three
representations that don't match:
- canonical key `normalize_ieee(ieee)` (e.g. `b0e8e8fffe16ef35`) = store key =
  emitter `unique_id`;
- emitter `entity_id` (UI-visible) = `infrared.ir_transmitter_b0_e8_e8_…_35`;
- `device.transmitter_id` — accepted unvalidated; the entity_id tail was stored,
  so resolution fails.

Bugs:
- **A — no normalize/validate on write.** `add_device`/`update_device` store
  `transmitter_id` verbatim (`storage.py:217,245`); garbage is silently accepted.
- **B — masking fallback.** `consumer.resolve_spec_transmitter` wraps an explicit
  lookup in bare `except Exception` → falls back to `resolve_transmitter(None)`,
  hiding the real cause and emitting the misleading "More than one transmitter".
- **C — orphan transmitters not reconciled.** A removed entry's transmitter
  lingers in the store (the fake `00:00…99`); prune only fires on future
  `async_remove_entry`, so pre-existing orphans persist → `resolve(None)` sees >1.
- **D — existing `device.transmitter_id` values are already wrong** (entity_id
  tail), need repair.

Fix (one canonical key everywhere):
1. **Reconcile** store transmitters against `hass.config_entries.async_entries(
   DOMAIN)` at setup; drop keys with no entry (self-heals orphans).
2. **`resolve_transmitter_ref(hass, store, ref)`** → canonical key (accepts key /
   colon-IEEE / emitter entity_id; strips `ir_transmitter_`, `:`, `_`); unknown →
   `ServiceValidationError`. Service write-paths normalize+validate via it; store
   defends that `transmitter_id` ∈ known keys.
3. **Remove masking fallback:** explicit-but-invalid `transmitter_id` → clear
   error; `resolve_transmitter(None)` only when unset.
4. **Migration v3→v4** repairs existing `device.transmitter_id` (normalize →
   match a store key, else `None`).
5. **Card UI:** pick the emitter from a list (store canonical key), not free text.
6. **Trailing-edge reconcile (confirmed live).** `ConsumerEntityManager.
   async_schedule_reconcile` drops signals that arrive while a reconcile is in
   flight (`if task and not task.done(): return`), so a burst of `update_command`s
   (e.g. assigning `feature: source` to several commands) leaves `source_list` /
   `supported_features` stale until an unrelated signal. Fix: track a "dirty"
   flag set on dropped signals and re-run reconcile once after the current one
   finishes (trailing edge), guaranteeing the final store state is reflected.
   Observed 2026-06-17: SELECT_SOURCE appeared but `source_list` only populated
   after an extra `update_device`.
7. **Expose transmitters in `list_commands`** (sanitized — no secrets). Today the
   response is `{locations: …}` only, so orphan transmitter records in the store
   are invisible to services; the smoke agent wrongly concluded "one transmitter"
   from emitter entities. Adding them makes orphans/reconcile observable and
   testable.

### Multi-transmitter PR (PR-MT) — scheduled after PR3d

Today 2+ transmitters are **not usable** even though the config flow allows
adding them. This PR makes them correct. Scope, in priority order:

1. **Sending must resolve a transmitter per device (highest priority — this is
   what actually breaks).** With >1 enabled transmitter, `resolve_transmitter(None)`
   raises `transmitter_required` (`storage.py:119-123`), and existing devices
   have `transmitter_id = None`. So adding a second transmitter **breaks IR send**
   for every device until each gets an explicit `transmitter_id`, and there is no
   UI for it (service `update_device` only). Fix: a usable assignment path —
   per-device transmitter selector in the card/UI, and/or auto-assign to the sole
   emitter at device creation, and a sensible default/error when ambiguous.
   Also wrap the resolve failure as `ServiceValidationError` (not raw 500).
1b. ✅ **Prune stale transmitter records from the store on entry removal.**
   Implemented in PR3c bundle. Deleted transmitter entries no longer count
   toward ambiguous default resolution after their config entry is removed.
2. **Decouple consumer-entity ownership from any transmitter config entry.** This
   single refactor closes BOTH documented lifecycle edges at once (owner-disable
   leaves consumer entities down; owner-removal purges entity customizations).
   Approach: own consumer entities/devices via a stable, hardware-independent
   owner rather than "the first transmitter entry". Do not patch the two edges
   separately, and do not re-introduce disable-vs-reload discrimination in
   `async_unload_entry` (that would revive F1).
3. **Mark multi-transmitter as supported in user docs** only once 1 & 2 land;
   until then note it as experimental.

Tests: per-device transmitter resolution (incl. ambiguous/stale id); ownership
decoupling survives owner disable/removal without losing entities or
customizations; existing single-transmitter behavior unchanged.

### Carried-over notes from the PR1/PR2 review (address in PR3)

- **(PR2) Verify the `via_device=("zha", ieee)` IEEE form** matches ZHA's device
  identifier exactly (lowercase colon form per `zha_adapter.py:36-37`). If it
  mismatches, the emitter device is created standalone (soft failure, no
  duplicate) but won't nest under the TS1201 — confirm in the real-HA smoke test.
- **(PR2) Emitter entity layer is unverified locally** (HA needs Python 3.14;
  `.venv314` exists). Real-HA smoke test owed: emitter appears, nests under the
  TS1201 device, and a test send goes through `ZHAAdapter`.
- **`transmitter_id` is stored but not validated against known transmitters**
  (`add_device`/`update_device`). The send path / `resolve_transmitter` must
  handle a stale or unknown `transmitter_id` gracefully — clear error or fall
  back to the single enabled transmitter — never raise an unhandled `KeyError`.
- **The registry dispatcher fires on every `async_save`**, including the startup
  `async_upsert_transmitter_from_entry`. The PR3 diff helper / per-platform
  subscribers must be **idempotent to redundant resync signals** (re-derive
  desired entities from the store and diff; do not blindly add).
- **Double-migration is redundant but safe:** `IRRegistryStore.async_load`
  re-runs `migrate_v1_to_v2` even though `_async_migrate_func` already ran. Leave
  as defensive or simplify — not a blocker.

### Remaining limitations (inherent to stateless IR)

- No real feedback: media/source/power state is **assumed**, not measured.
- `power_toggle`-only devices cannot guarantee on/off correctness after external
  manual changes.
- Volume is step-based; no absolute volume level unless the device exposes it.
- A `zosung_base64 -> raw timings` decoder is **not required** (the framework
  never calls `get_raw_timings()` on send — see Spike results). It is an optional
  follow-up for interoperability with third-party emitters only; v1 carries the
  opaque code in a `ZosungCommand` and the emitter forwards it to `ZHAAdapter`.
- Assist/LLM **exposure** of newly created entities depends on the user's HA
  exposure settings (opt-in). The integration creates the entities
  automatically but cannot — and must not — force them into Assist; document the
  one-time "expose new entities automatically" toggle for users who want every
  new IR device available to voice/LLM immediately.

---

## Spike results

**CLOSED.** Verified against `home-assistant/core` (`dev`,
`homeassistant/components/infrared/`) and `infrared-protocols==6.0.1` — read
directly from GitHub source, no live HA introspection needed.

Directory contents: `__init__.py`, `const.py`, `entity.py`, `helpers.py`,
`icons.json`, `manifest.json`, `strings.json`. Integration type `entity`,
quality scale `internal`, requirement `infrared-protocols==6.0.1`.

Confirmed API surface (verbatim from source):

- **Command type is an alias:** `from infrared_protocols.commands import Command
  as InfraredCommand`. `InfraredCommand` == `infrared_protocols.commands.Command`.
- **`InfraredDeviceClass(StrEnum)`**: `EMITTER = "emitter"`, `RECEIVER =
  "receiver"`.
- **Emitter:** `InfraredEmitterEntity.async_send_command(self, command:
  InfraredCommand) -> None` is **abstract** — our emitter implements it. `state`
  is a `@final` property (timestamp of last command sent).
- **🔑 The framework does NOT call `get_raw_timings()` on the send path.**
  `async_send_command_internal` (`@final`) is exactly:
  ```python
  await self.async_send_command(command)
  self.__last_command_sent = dt_util.utcnow().isoformat(timespec="milliseconds")
  self.async_write_ha_state()
  ```
  It only delegates to the subclass and stamps state. So our emitter can read
  any attribute it likes off the command object.
- **Consumer helper** (`helpers.py`):
  ```python
  async def async_send_command(hass, entity_id_or_uuid: str,
      command: InfraredCommand, context: Context | None = None) -> None
  ```
  Resolves the entity, asserts it `isinstance InfraredEmitterEntity`, optionally
  sets context, then `await entity.async_send_command_internal(command)`. Raises
  `HomeAssistantError` if not found. (Accepts entity_id **or** uuid via
  `er.async_validate_entity_id`.)
- **Consumer base class** (`helpers.py`): `InfraredEmitterConsumerEntity`
  declares a class attribute `_infrared_emitter_entity_id: str` (subclass
  populates it) and sends via:
  ```python
  async def _send_command(self, command: InfraredCommand) -> None:
      await async_send_command(self.hass, self._infrared_emitter_entity_id,
                               command, context=self._context)
  ```
- **Manifest:** the `infrared` integration itself is `integration_type: entity`;
  consumers declare `"dependencies": ["infrared"]`.

### Resolved decision — Path B is clean and (near-)canonical

Because the framework never calls `get_raw_timings()` on send, **no
`zosung -> raw` decoder is required** for v1:

1. Define a small `Command` subclass (e.g. `ZosungCommand(Command)`) carrying our
   opaque `code: str` (and `format`). Implement `get_raw_timings()` to raise
   `NotImplementedError` (only ever called by *foreign* emitters, which we don't
   target).
2. Consumer entities subclass / mirror `InfraredEmitterConsumerEntity`, set
   `_infrared_emitter_entity_id` to our emitter, and send via the **standard**
   `infrared.async_send_command(...)` helper.
3. Our `InfraredEmitterEntity.async_send_command(command)` reads `command.code`
   and forwards it to `ZHAAdapter` — transport stays in one place.

This routes through the real platform helper + real emitter entity (canonical),
with the only deviation being an opaque-payload command. The `zosung -> raw`
decoder is now a **pure interoperability follow-up** (so third-party emitters
could send our codes), **not** a prerequisite — downgrade it from "limitation"
to "optional enhancement".

Residual nit to confirm while coding PR2 (non-blocking): the exact `Command`
base `__init__` / required fields in `infrared-protocols==6.0.1` (so the
`ZosungCommand` subclass constructs cleanly). Read from the installed package
during PR2.

PR2 nit confirmed from installed `infrared-protocols==6.0.1`:
`Command.__init__(self, *, modulation: int, repeat_count: int = 0) -> None`.
Required field: `modulation`; stored fields: `modulation`, `repeat_count`.
`get_raw_timings()` remains abstract, but HA's infrared emitter send path calls
our `InfraredEmitterEntity.async_send_command(command)` and does not call
`get_raw_timings()`.

PR2 DeviceInfo decision: the emitter uses its own HA device entry with
`identifiers={(DOMAIN, transmitter_id)}` and `via_device=("zha", ieee)` instead
of claiming the ZHA identifier directly. This avoids metadata churn on the ZHA
TS1201 device while preserving the explicit device graph relation.

PR2/PR3 test harness note: Python 3.14.6 and `.venv314` are now available with
`homeassistant==2026.6.3`, `infrared-protocols==6.0.1`, and
`pytest-homeassistant-custom-component`. PR2 still keeps only pure command tests;
PR3 must add a real-HA smoke/entity test that verifies the emitter appears,
uses the intended device relation, and routes `ZosungCommand` to
`ZHAAdapter.async_send`.

PR3a harness note: on this Windows workspace,
`pytest-homeassistant-custom-component` auto-loading currently fails before test
collection because `homeassistant.runner` imports POSIX-only `fcntl`. PR3a uses
plain pytest with plugin autoload disabled for focused send-path tests; the
full Home Assistant entity smoke test remains a PR3/real-HA runtime gate.

PR3a review follow-up: consumer-owner re-election now schedules a normal reload
of the newly elected owner via `hass.config_entries.async_schedule_reload()`
instead of forwarding consumer platforms from another entry's unload flow.
Remote registry reconciliation is guarded by an `asyncio.Lock`; dispatcher
bursts coalesce to one pending task, and pending reconcile work is cancelled on
platform unload. Before PR3b, run a real HA 2026.6.x smoke test for one and two
transmitters, including owner unload/re-election.
