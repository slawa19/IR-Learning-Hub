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

## MVP Hardening

- Improve user-facing error messages in the card.
- Add automated tests for storage and service validation.
- Add compatibility notes for specific Home Assistant versions.
- Add screenshots or short workflow captures.

## Post-MVP Candidates

- Multiple transmitter UX.
- SmartIR-compatible export for portability.
- Additional ZHA IR transmitter profiles.
- Optional Zigbee2MQTT transport adapter.
- Better handling for repeated-frame or long-press remote protocols.
- Device-type templates for common media commands.

## Non-Goals for the Current Architecture

- Tuya Cloud runtime.
- Smart Life runtime.
- Home Assistant core patches.
- Monkey patching ZHA internals.
- Helper entities as the primary storage model.
- Built-in public IR code database.
