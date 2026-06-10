# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses pre-release versioning while the integration stabilizes.

## Unreleased

### Added

- Native ZHA custom integration for the Tuya TS1201 / MOES UFO-R11 IR blaster.
- Config flow for transmitter setup.
- ZHA learn, read, test, and send services.
- Async `learn_and_read` workflow.
- Store-backed IR command registry.
- Registry create, rename, delete, list, save, and send services.
- Diagnostic status sensor.
- Bundled Lovelace card.
- English repository documentation.

### Known Issues

- The repository metadata in `manifest.json` still uses placeholder GitHub URLs.
- The supported device profile is currently limited to `ts1201_zosung`.
- The TS1201 learned-code attribute is volatile after restart; saved commands remain persistent.