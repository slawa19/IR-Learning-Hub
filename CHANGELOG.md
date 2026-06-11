# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses pre-release versioning while the integration stabilizes.

## Unreleased

No unreleased changes yet.

## 0.1.13 - 2026-06-11

### Fixed

- Prevented duplicate Lovelace card custom-element registration when Home Assistant loads the card module more than once in the same browser session.

## 0.1.12 - 2026-06-11

### Added

- Added a Lovelace card screenshot to the README for GitHub and HACS rendering.

### Changed

- The Lovelace card JavaScript is now served without long-lived cache headers, so users no longer need to change the resource query string after integration updates.

## 0.1.11 - 2026-06-11

### Added

- Added an internal IR format layer with normalized raw timings and Zosung base64 encoding/decoding.
- Added Sony SIRC generation through the `ir_learning_hub.generate_code` service.
- Added a local `tools/generate_sony_str_db840_profile.py` utility for generating a Lovelace-card-importable Sony STR-DB840 profile.

### Changed

- Device profile import now preserves optional command `source` provenance.
- The Lovelace card header now keeps only the status indicator, with a tooltip, and removes the manual refresh button.
- README and installation docs now focus on end-user setup and current card/service workflows.

### Validated

- Sony SIRC generation was validated on a Sony STR-DB840 receiver with the `Power` command.

## 0.1.10 - 2026-06-11

### Fixed

- Profile import now ignores malformed command icons instead of aborting the import. Valid `mdi:*` icons are still imported.

### Changed

- Installation docs now describe the card icon lookup order: integration root `icon.png`, then `brand/icon.png` fallback.

## 0.1.9 - 2026-06-10

### Changed

- README now presents IR Learning Hub as a functional integration and reflects the current setup, card, service, localization, export/import, and HACS release workflow.

## 0.1.8 - 2026-06-10

### Changed

- Documentation now reflects the current Lovelace card workflow, command icons, profile export/import, and the `update_command` service.

## 0.1.7 - 2026-06-10

### Fixed

- Profile export copy now falls back to textarea-based copying when the browser Clipboard API is unavailable.

## 0.1.6 - 2026-06-10

### Fixed

- Export and import profile actions now open from the device menu even when the device is not selected in the sidebar.
- Export/import panel no longer stretches the card: JSON keeps its formatting and scrolls instead of wrapping, and the action buttons wrap on narrow cards.
- Card no longer re-renders on every Home Assistant state update, which previously caused hover flicker, dropped clicks, and lost input focus while typing.

### Changed

- Export/import panel buttons are now icon-only with tooltips, matching the rest of the card.
- Add-location, add-device, and new-command forms are more compact: inline placeholder hints, a "?" tooltip for the ID rule, and icon-only confirm/cancel buttons.
- The header refresh button is now labelled "Reload list" to clarify that it re-reads the registry after external changes.

## 0.1.5 - 2026-06-10

### Changed

- Updated README and installation examples to match the latest release version.

## 0.1.4 - 2026-06-10

### Fixed

- Added repository-level brand assets so HACS can show the integration icon in its downloaded repositories list.
- Published a new release so HACS can refresh update metadata and changelog information.

## 0.1.3 - 2026-06-10

### Added

- Command action menus now support renaming, deleting, relearning, and choosing icons without cluttering the remote layout.
- Device profiles can now be exported and imported as JSON for moving commands to another remote.
- Commands can now keep a custom icon when they are relearned.

### Fixed

- Fixed the bundled card icon path so `/ir_learning_hub/icon.png` loads correctly after installation.
- Fixed profile import validation so invalid command IDs are caught before any commands are saved.
- Fixed dropdown menus so they are no longer clipped by the sidebar.

## 0.1.2 - 2026-06-10

### Changed

- HACS now hides the default branch download option so users see release versions instead of commit IDs.

## 0.1.1 - 2026-06-10

### Added

- HACS-ready release metadata, including an integration icon.
- English, Russian, and Ukrainian translations for setup, services, status sensor states, and user-facing errors.

### Changed

- The Lovelace card now uses a cleaner remote-control layout with a location/device tree and a guided command-learning flow.
- New location, device, and command forms now ask for the display name first and generate the technical ID automatically.
- HACS installation instructions now point users to release tags instead of commit hashes.

### Fixed

- Fixed a UI bug where name and ID input fields could disappear in the Lovelace card.
- Fixed command sending status so the integration no longer looks stuck in `sending` after a successful send.
- Fixed several learning-flow cleanup issues that could leave stale timers or background learning tasks active.
- Fixed setup handling when a detected ZHA transmitter becomes unavailable while the form is open.

### Known Issues

- The supported device profile is currently limited to `ts1201_zosung`.
- The TS1201 learned-code attribute is volatile after restart; saved commands remain persistent.
