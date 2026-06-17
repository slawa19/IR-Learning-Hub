# Roadmap

This roadmap describes the intended direction of the project. It is not a release guarantee.

## Completed / Validated

- Native ZHA learn command for TS1201 / MOES UFO-R11.
- Native ZHA send command for saved Zosung payloads.
- Backend read of learned code from ZHA attribute `0`.
- Async `learn_and_read` service.
- Store-backed command registry.
- Registry CRUD services.
- Diagnostic status sensor.
- Lovelace card served by the integration.
- Command icons and metadata updates without relearning.
- Device-profile export and import through the Lovelace card.
- HACS release metadata, repository icon assets, and release-based installation.
- Internal raw timing model and Zosung encoder/decoder.
- Sony SIRC generation through `generate_code`, validated on Sony STR-DB840 power control.
- Local utility for generating a Sony STR-DB840 card-import profile.
- Native Home Assistant `infrared` emitter entities for configured TS1201 transmitters.
- Registry-backed native `remote`, `media_player`, and `switch` consumer entities.
- Entity-first registry projection with explicit per-command `feature` roles and capability inference.
- Multiple transmitters via the hub + config-subentries model.
- Canonical transmitter identity (normalization, validation, orphan reconciliation).
- Real Home Assistant 2026.6.x validation with a TS1201 blaster: migration, entity exposure, and physical IR sends confirmed.

## MVP Hardening

- Improve user-facing error messages in the card.
- Add a card affordance for assigning command `feature` roles in bulk.
- Add compatibility notes for specific Home Assistant versions.
- Add screenshots or short workflow captures of the entity/Assist flow.
- Live-verify the multi-transmitter UI flow (add/remove a second transmitter subentry) and N>=2 migration.

## Post-MVP Candidates

- SmartIR-compatible export for portability.
- Additional ZHA IR transmitter profiles.
- Optional Zigbee2MQTT transport adapter.
- Better handling for repeated-frame or long-press remote protocols.
- Device-type templates for common media commands.
- Additional protocol generators and importers such as Pronto Hex, raw timings, and LIRC `raw_codes`.

## Non-Goals for the Current Architecture

- Tuya Cloud runtime.
- Smart Life runtime.
- Home Assistant core patches.
- Monkey patching ZHA internals.
- Helper entities as the primary storage model.
- Built-in public IR code database.
