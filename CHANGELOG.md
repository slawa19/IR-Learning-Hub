# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses pre-release versioning while the integration stabilizes.

## Unreleased

No unreleased changes yet.

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
