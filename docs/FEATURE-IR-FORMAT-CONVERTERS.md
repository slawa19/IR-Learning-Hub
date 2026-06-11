# Feature Request: IR Format Converters and Import

Status: Proposed (future work)
Owner: unassigned
Related: [ROADMAP.md](ROADMAP.md), [ARCHITECTURE.md](ARCHITECTURE.md), [SERVICES.md](SERVICES.md)

## Summary

Add the ability to import IR commands that were **not** learned by the local
TS1201, by converting common interchange formats into the Zosung payload the
integration already sends. The feature is delivered as a chain of format
converters built around a single internal raw-timing model:

```text
Pronto Hex ─┐
LIRC        ├─> normalized raw timings ──> tuya_base64 (zosung) ──> existing send path
raw timings ┘
```

This is an **import / conversion tool**, not a bundled IR code database. A
built-in public IR database remains a Non-Goal (see
[ROADMAP.md](ROADMAP.md) and [ARCHITECTURE.md](ARCHITECTURE.md)); this feature
lets users bring codes they already have (forum dumps, Pronto exports, LIRC
configs) and store them as normal commands.

## Motivation

Today the integration only stores opaque `zosung_base64` strings produced by the
TS1201 during learning (`save_command` in
[`storage.py`](../custom_components/ir_learning_hub/storage.py); send path in
[`zha_adapter.py`](../custom_components/ir_learning_hub/zha_adapter.py)). There is
no way to populate a command without physically pressing a button on a remote.

The Tuya/Zosung payload format is **already reverse-engineered and documented**:

```text
zosung_base64 = base64( FastLZ( IR timings as uint16 little-endian, microseconds ) )
```

FastLZ is the level‑1 LZ77 variant (8 KB window). Reference implementations of the
codec exist publicly. This means the hardest-looking link — `raw timings ->
zosung_base64` — is a known, testable transform rather than a research project,
which de-risks the whole feature.

### References

- Tuya IR compression scheme documentation: <https://gist.github.com/mildsunrise/1d576669b63a260d2cff35fda63ec0b5>
- irtuya decoder/converter: <https://github.com/pasthev/irtuya>
- NEC -> Tuya (ZS06/ZS08/TS1201) encoder: <https://gist.github.com/andrewcchen/f16eb20d19ea64d9f997c470e2addeaa>
- Broadlink -> Tuya converter: <https://gist.github.com/svyatogor/7839d00303998a9fa37eb48494dd680f>
- FastLZ: <https://ariya.github.io/FastLZ/>

## Goals

- Convert `zosung_base64 <-> raw timings` locally, with a verified round trip.
- Import Pronto Hex and raw timings into normal saved commands.
- Import the simple LIRC `raw_codes` form.
- Keep the converters transport-agnostic and reusable (a pure-Python module with
  no Home Assistant dependency), so they can be unit-tested in isolation.

## Non-Goals

- No bundled / scraped public IR code database.
- No LIRC protocol-config decoding (`SPACE_ENC`, `RC5/RC6/RCMM`, `pre_data`,
  `toggle`, …) in the first iteration — deferred and low priority.
- No Broadlink or Global Caché import in the first iteration — deferred.
- No change to the ZHA send/learn transport.

## Key Design Decisions

### 1. One internal model

All converters target a single normalized representation:

```json
{
  "carrier_frequency": 38000,
  "duty_cycle": 0.33,
  "timings": [9000, 4500, 560, 560, 560, 1690],
  "repeat": 0
}
```

`timings` is an alternating list of mark/space durations in microseconds.
Converters are written as `format -> raw` (decoders) and `raw -> format`
(encoders); they never convert format-to-format directly.

Protocol encoders must return the **complete physical signal that should be
sent by the transmitter**, not just one abstract protocol frame. If a protocol
requires repeats or frame-period padding for reliable receiver recognition, the
encoder expands those repeats and inter-frame spaces directly into `timings`
before the raw signal is passed to the Zosung encoder. The `repeat` field is
reserved for formats that explicitly model repeat blocks; it must not be relied
on to make the TS1201 repeat a protocol frame unless that behavior has been
validated on hardware.

### 2. The codec is the linchpin, built and validated first

`raw <-> zosung_base64` is implemented and round-trip-validated against
**real codes learned by the user's own TS1201** before any front-end importer is
written. Everything downstream is useless without a trusted codec, and the round
trip is also how we confirm that the payload the TS1201 returns over ZHA is
byte-compatible with the documented Tuya cloud format (it may differ in framing
or carrier handling). Acceptance: `decode -> encode -> send` reproduces a working
command on physical hardware.

### 3. Carrier frequency is explicit and validated

The raw/Tuya format does **not** carry a carrier frequency; the TS1201 transmits
at ~38 kHz. Pronto **does** carry frequency. When an imported code's carrier is
not ~38 kHz (e.g. 36/40/56 kHz devices, some Sony / RC‑MM), the converter must
**warn** the user rather than silently emit a payload that will not actuate the
target device.

For Sony SIRC, a 40 kHz source frequency should be treated as an informational
warning rather than a likely failure. Sony receivers are usually tolerant enough
that a TS1201 transmitting near 38 kHz can still actuate 40 kHz SIRC commands.

### 4. Protocol logic is borrowed, not reimplemented

If protocol-level encoding (NEC, Samsung, RC5, Sony, …) is added later, lean on
the encoders in IRremoteESP8266 as the source of truth rather than reimplementing
LIRC's protocol math. Out of scope for the PRs below; noted for direction.

## Storage Model Changes

Current command record (see `save_command` in
[`storage.py`](../custom_components/ir_learning_hub/storage.py)):

```json
{
  "name": "Power",
  "code": "<base64>",
  "format": "zosung_base64",
  "verified": true,
  "updated_at": "…",
  "icon": "mdi:power"
}
```

Target record adds optional provenance fields (all backward compatible):

```json
{
  "name": "Power",
  "code": "<base64>",
  "format": "zosung_base64",
  "carrier_frequency": 38000,
  "source_format": "pronto",
  "verified": false,
  "updated_at": "…",
  "icon": "mdi:power"
}
```

- `code` / `format` keep their current meaning; `zosung_base64` stays the value
  that is actually transmitted.
- `source_format` records where the code came from (`learned`, `pronto`, `raw`,
  `lirc_raw`, …) for display and re-export.
- `carrier_frequency` is informational and drives the frequency-mismatch warning.
- Imported commands are saved with `verified: false` until tested, matching the
  existing learn-then-test workflow.

`STORAGE_VERSION` is bumped from `1` to `2` with a no-op forward migration
(missing fields default; nothing is rewritten destructively).

## PR Breakdown

Each PR is independently reviewable and shippable. Order matters: PR 1 and PR 2
are prerequisites for everything else.

### PR 1 — Internal raw model + storage schema

**Goal:** introduce the normalized model and the storage fields the converters
need, with no user-visible behavior change yet.

**Scope:**
- New pure module (e.g. `ir_formats/model.py`) defining the raw-timing model and
  small helpers (validation, mark/space sanity checks).
- Extend the command record with optional `source_format` and
  `carrier_frequency`; thread `code_format` is already present in
  `save_command`.
- Bump `STORAGE_VERSION` to `2` with a forward migration in
  [`storage.py`](../custom_components/ir_learning_hub/storage.py)
  (`async_load` / `_default_data`).
- Update [ARCHITECTURE.md](ARCHITECTURE.md) "Storage Model" section.

**Acceptance:**
- Existing stores load unchanged; new fields default cleanly.
- Unit tests for model validation and the migration.

**Out of scope:** any conversion logic, any UI.

### PR 2 — Zosung codec (`raw <-> zosung_base64`)

**Goal:** the linchpin transform, validated end to end.

**Scope:**
- FastLZ (level 1) compress/decompress.
- `decode_zosung(base64) -> raw` and `encode_zosung(raw) -> base64`
  (uint16‑LE microsecond timings).
- A small developer/validation entry point (script or test fixture) that runs the
  round trip on captured real codes.

**Acceptance:**
- Round trip on a corpus of real learned codes:
  `decode -> encode` is byte-identical (or functionally identical where FastLZ
  allows multiple encodings).
- Manual hardware check documented: a decoded-then-re-encoded code still actuates
  the device via the existing send path.
- Decoder rejects malformed input with a clear error.

**Out of scope:** wiring into services or the card.

### PR 3 — Pronto Hex -> raw

**Goal:** first user-facing importer front-end.

**Scope:**
- `decode_pronto(hex) -> raw`, including carrier frequency from the Pronto
  header and both once/repeat burst pairs.
- Carrier-mismatch warning surfaced to the caller (not just logged).
- New service `import_command` (and/or extend `save_command`) that accepts a
  `source_format` + payload, converts to `zosung_base64`, and stores it via the
  existing registry path. Document in [SERVICES.md](SERVICES.md).

**Acceptance:**
- Known Pronto samples convert to expected timings within tolerance.
- A converted Pronto code can be saved and sent.
- Non‑38 kHz import produces a visible warning.

### PR 4 — Raw timings import + card UI

**Goal:** manual import path for debugging and forum dumps, plus the first card
surface for importing.

**Scope:**
- Accept a raw timings list (with optional carrier) through `import_command`.
- Card: an "Import command" entry in the device/command menu with a format
  selector (`Pronto`, `Raw`) and a paste field, calling the new service.
- Show `source_format` on imported commands; keep them `verified: false` until
  tested with the existing test action.

**Acceptance:**
- A pasted raw/Pronto code becomes a saved, testable command from the card.
- UI follows the existing boundary: card calls `ir_learning_hub.*` services only
  (see [ARCHITECTURE.md](ARCHITECTURE.md) "UI Boundary").

### PR 5 — LIRC `raw_codes` import

**Goal:** import the simple, unambiguous LIRC form.

**Scope:**
- Parse `begin raw_codes … end raw_codes`, mapping each named entry to a raw
  command; default carrier to 38 kHz unless the config specifies otherwise.
- Add `lirc_raw` to the format selector.

**Acceptance:**
- A real LIRC `raw_codes` file imports each named button as a separate command.
- Decoded LIRC protocol configs (non‑`raw_codes`) are explicitly rejected with a
  message pointing at the deferred work below.

### Deferred (post-feature, separate proposals)

Not part of this feature's initial delivery; listed for direction:

- LIRC protocol configs (`SPACE_ENC`, `RC5/RC6/RCMM`, `pre_data`/`post_data`,
  `toggle`, `REVERSE`, `CONST_LENGTH`).
- Protocol encoders (NEC/Samsung/RC5/Sony/…) sourced from IRremoteESP8266 logic.
- Sony SIRC protocol encoder details: command bits are sent LSB-first; Sony12 is
  `7 command bits + 5 device bits`; each frame starts with `2400/600`, uses
  `600/600` for `0` and `1200/600` for `1`, and must be sent at least three
  times with a 45 ms frame period. The encoder must expand those repeats into
  the returned raw timings, for example `frame + gap` repeated three times,
  where `gap = 45000 - sum(frame)`.
- Broadlink base64 import (for SmartIR portability).
- Global Caché `sendir` import.

## Testing Strategy

- Pure converter module is unit-tested with no Home Assistant runtime.
- A captured corpus of real TS1201 codes anchors the codec round-trip tests.
- One documented manual hardware validation per front-end (Pronto, raw, LIRC):
  import -> test -> device actuates.

## Risks and Open Questions

- **ZHA payload vs. Tuya cloud format parity** — resolved empirically by the
  PR 2 round trip. If they differ, PR 2 absorbs the adaptation before any
  front-end ships.
- **Carrier handling on the TS1201** — whether the device honors any embedded
  frequency or always uses ~38 kHz. Drives how strict the mismatch warning is.
- **Licensing** — LIRC configs and some interchange samples carry their own
  licenses; this feature only converts user-supplied input and bundles no
  database, which keeps the repo's licensing situation unchanged (see
  [README.md](../README.md)).
