# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project uses pre-release versioning while the integration stabilizes.

## Unreleased

No unreleased changes yet.

## 0.3.4 - 2026-06-21

### Fixed

- Re-released the Lovelace resource sync fix with the correct tagged version so HACS installs the patched files instead of the older 0.3.0 build.

## 0.3.3 - 2026-06-21

### Fixed

- The embedded Lovelace card now uses the standard Home Assistant pattern again: a single module resource whose URL is auto-synced with a version query string, so upgrades do not require manual resource edits and do not depend on custom loaders.
- The card resource auto-`?v=` sync now runs after Home Assistant startup and no longer depends on a private Lovelace resource-mode attribute, making post-restart resource updates reliable on live installs.

## 0.3.2 - 2026-06-21

### Fixed

- `media_player.async_mute_volume` now treats a lone `mute` command as a toggle, so both mute and unmute service calls succeed on toggle-only devices instead of raising a Home Assistant 500.
- Hub setup now self-heals orphaned virtual consumer devices left behind in the device registry when the backing store device no longer exists.
- The Lovelace card no longer rebuilds its full shadow DOM or flickers on command press; stateless command buttons now show local fading send feedback instead of a global sending/sent banner.

### Changed

- IR send debug logging now explicitly reports dispatch to ZHA without implying confirmed delivery or physical IR emission.

## 0.3.1 - 2026-06-21

### Fixed

- Prevented transmitter reconciliation from wiping the registry when setup runs before any transmitter subentries are available, and avoided redundant registry saves/reloads when nothing changed.
- Self-healed migrated transmitter devices that still carried a stale entry-level association, normalized hub titles to `IR Learning Hub`, and made config-entry updates reload only when transmitter subentries actually changed.
- Added config-entry device removal support for virtual consumer devices so removing a Home Assistant device also deletes the matching registry IR device.
- Hardened transmitter resolution and logging around consumer entities so mismatched IEEE formatting and unavailable emitters fail clearly instead of disappearing silently.

## 0.3.0 - 2026-06-17

### Added

- Added native `media_player` consumer entities for AV devices, with features
  (play/pause/stop/next/previous, volume step, mute, source select) derived from
  each command's explicit role. `media_player.select_source` resolves the source
  by its human-readable label.
- Added native `switch` consumer entities for pure on/off IR devices.
- Added an explicit per-command `feature` role (closed vocabulary such as
  `power_on`, `play`, `volume_up`, `source`). Capabilities are now inferred from
  this role, not from free-text `command_id`, so any command naming works. A v3
  storage migration seeds the role from canonical legacy command IDs.
- Multi-transmitter support via the canonical Home Assistant model: the
  integration is now a **single hub config entry**, and each transmitter is a
  **config subentry** with its own emitter. Add/remove transmitters from the hub.

### Changed

- Restructured to one hub config entry + transmitter subentries, removing the
  earlier owner-election machinery. A one-time migration reshapes legacy
  one-entry-per-transmitter installs into the hub model; learned commands are
  preserved (the registry store is untouched).
- Canonical transmitter identity: `transmitter_id` references are normalized and
  validated on write (accepting the canonical key, IEEE, or emitter entity id);
  orphaned transmitter records are reconciled against existing subentries.
- `update_command` now also sets a command's `feature` role.
- `media_player`/`switch`/`remote` consumer entities share a common base and
  refresh immediately on registry changes (no extra service call needed).

### Notes

- Validated on real Home Assistant 2026.6.x with a TS1201/Zosung blaster:
  migration, entity exposure, and real IR sends (media_player and remote) were
  confirmed against physical devices.
- Assist/LLM exposure remains Home Assistant policy controlled — enable entity
  exposure in voice assistant settings to use the new entities with Assist.

## 0.2.0 - 2026-06-16

### Added

- Added the Home Assistant `infrared` emitter platform: each configured TS1201 transmitter now appears as an infrared emitter entity.
- Added registry-backed `remote` consumer entities for stored IR devices, controlled through Home Assistant's infrared helper path.
- Added entity-first storage foundations: registry v2 migration, `preferred_domain`, `transmitter_id`, and registry update dispatcher signals.
- Added command capability inference and canonical command-id alias normalization.
- Added `update_device` so device metadata, preferred domain, and transmitter assignment can be changed through services.

### Changed

- The integration now depends on Home Assistant's native `infrared` integration and requires Home Assistant 2026.6 or newer.
- Consumer entities route through the emitter entity and never import or call the ZHA adapter directly.
- Config-entry ownership now keeps consumer entities on a single owner entry and schedules a reload when ownership moves.

### Notes

- `media_player` and `switch` consumer entities are intentionally deferred to the next iteration; this release exposes the emitter and generic `remote` entities first.
- Assist/LLM exposure remains Home Assistant policy controlled. Enable entity exposure in Home Assistant voice assistant settings if you want new IR remotes available to Assist.
- A full real-HA smoke test with one and two transmitters is still required before building the next consumer-domain layer.

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
