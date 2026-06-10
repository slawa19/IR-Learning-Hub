# IR Learning Hub

IR Learning Hub is a local Home Assistant custom integration for learning, storing, testing, organizing, exporting, importing, and replaying infrared commands through a ZHA-connected Tuya TS1201 / MOES UFO-R11 IR blaster.

It turns the TS1201 from a low-level ZHA device into a usable remote-control hub: learn a button from a physical remote, test it, save it under a stable command ID, replay it from Home Assistant services, and manage the command library from a Lovelace card.

The integration is intentionally local-first. It uses Home Assistant's native ZHA runtime and does not require Tuya Cloud, Smart Life, Zigbee2MQTT, SmartIR, IR Wrapper, scripts, or helper entities for the main command path.

## What It Does

- Discovers supported ZHA IR transmitters during setup, with manual setup as a fallback.
- Starts TS1201 learning mode and reads the learned IR code from ZHA.
- Sends raw learned codes for testing before saving.
- Stores verified commands in Home Assistant storage.
- Organizes commands as `Location -> IR device -> Command`.
- Exposes a stable Home Assistant service API for automations, scripts, and Developer Tools.
- Provides a bundled Lovelace card for day-to-day use.
- Supports command rename, relearn, delete, and optional `mdi:*` icons without replacing the stored IR code.
- Exports and imports one device profile as JSON, so a command set can be moved to another logical remote without relearning.
- Provides localized setup, services, sensor states, errors, and card UI in English, Russian, and Ukrainian.

## Current State

IR Learning Hub is a functional Home Assistant custom integration for the confirmed TS1201 / MOES UFO-R11 ZHA path.

The implemented flow covers the full command lifecycle:

1. Select a supported ZHA transmitter in the config flow.
2. Create locations and IR devices.
3. Learn a command from a physical remote.
4. Test the captured IR code.
5. Save it with a stable ID and display name.
6. Replay it from the Lovelace card, Home Assistant services, automations, or scripts.
7. Maintain the library with rename, relearn, icon, delete, export, and import actions.

Saved commands survive Home Assistant restarts because they are stored through Home Assistant's `Store` API. The TS1201's last-learned-code attribute is volatile, so `read_last_code` can return `code_empty` after a restart until a new button is learned. This does not affect already saved commands.

The integration currently targets one confirmed hardware/profile combination. The architecture keeps the transport layer isolated so additional ZHA IR transmitter profiles can be added later without changing the registry or UI model.

## Supported Hardware

The confirmed profile is:

| Field | Value |
| --- | --- |
| Device | Tuya TS1201 / MOES UFO-R11 |
| Manufacturer | `_TZ3290_ot6ewjvmejq5ekhl` |
| Quirk | `zhaquirks.tuya.ts1201.ZosungIRBlaster` |
| Endpoint | `1` |
| IR control cluster | `0xE004` / `57348` |
| Learn command | `1` |
| Send command | `2` |
| Learned-code attribute | `0` |

Cluster `0xED00` / `60672` may also appear on the device, but the integration uses cluster `0xE004` because learn and send are confirmed there for the supported profile.

## Lovelace Card

The bundled card is the intended daily interface.

It provides:

- a tree of locations and IR devices;
- inline add forms with name-first entry and automatic ID generation;
- remote-style command buttons;
- one-click sending;
- command relearn from the command menu;
- a three-step learning wizard;
- command icon selection with `mdi:*` support;
- inline rename actions;
- delete confirmations;
- device-profile export/import;
- manual registry refresh after external changes.

Example card configuration:

```yaml
type: custom:ir-learning-hub-card
title: IR Learning Hub
status_entity: sensor.ir_learning_hub_status
timeout: 60
poll_interval: 2
```

The card uses only `ir_learning_hub.*` services. It does not talk to ZHA directly.

## Service API

IR Learning Hub exposes services under the `ir_learning_hub` domain:

- `learn`
- `read_last_code`
- `learn_and_read`
- `test_code`
- `save_command`
- `send_command`
- `list_commands`
- `add_location`
- `add_device`
- `add_command`
- `update_command`
- `rename_location`
- `rename_device`
- `rename_command`
- `delete_location`
- `delete_device`
- `delete_command`

The Lovelace card is built on top of the same services that automations and scripts can use.

Example saved-command replay:

```yaml
service: ir_learning_hub.send_command
data:
  location_id: cabinet
  ir_device_id: cd_player
  command_id: open_close
```

For complete schemas, response data, and error codes, see [docs/SERVICES.md](docs/SERVICES.md).

## Installation

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for detailed installation, update, and HACS notes.

### HACS

Add this repository as a HACS custom repository with category `Integration`:

```text
https://github.com/slawa19/IR-Learning-Hub
```

Install a GitHub release/tag whose version matches `custom_components/ir_learning_hub/manifest.json`. For example, release tag `v0.1.9` must contain:

```json
"version": "0.1.9"
```

Do not install a raw commit SHA as a HACS version. HACS validates versions and may reject commit hashes such as `fb1af13`. Publish releases with semantic git tags such as `v0.1.9` so HACS can show normal version numbers and release notes.

### Lovelace Resource

Add the bundled card as a Lovelace resource:

```yaml
url: /ir_learning_hub/ir-learning-hub-card.js?v=9
type: module
```

After updating the card, bump the query string and hard-refresh the browser if Home Assistant still serves the old JavaScript.

## Basic Usage

Recommended card flow:

1. Add a location.
2. Add an IR device inside that location.
3. Add a command. Enter the display name first; the card generates the ID automatically.
4. Start learning.
5. Point the physical remote at the TS1201 and press the desired button.
6. Test the learned code or skip testing.
7. Save the command.
8. Send it from the command grid.

Service-only flow:

1. Call `ir_learning_hub.learn_and_read` with response data enabled.
2. Point the physical IR remote at the TS1201 and press the desired button.
3. Use the returned `code` with `ir_learning_hub.test_code`.
4. If the target device responds, save it with `ir_learning_hub.save_command` and `verified: true`.
5. Replay the saved command with `ir_learning_hub.send_command`.

Example `save_command` data:

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
code: "<base64-code>"
verified: true
```

IDs must match `[a-z0-9_]+`. Display names can be normal human-readable text.

## Command Library

The registry is structured like this:

```text
transmitter
  location
    IR device
      command
```

Command records store the learned code, display name, format, verification flag, update timestamp, and optional display icon. Relearning a command replaces the IR code but preserves its icon.

The device profile export/import feature exports one IR device's commands as JSON. Import writes those commands into the device selected from the menu and uses the same backend services as the card.

## Home Assistant Integration Details

- Storage: Home Assistant `Store`.
- Main transport: Home Assistant ZHA.
- Frontend: bundled Lovelace custom card served by the integration.
- Status: translated diagnostic sensor.
- Localization: `strings.json` and `translations/*.json` for backend surfaces, plus a card-side translation table.
- HACS: release/tag based installation with repository icon assets under `brand/`.

## Why Native ZHA

The TS1201 exposes useful IR functionality through vendor-specific ZHA behavior rather than a polished Home Assistant entity model. IR Learning Hub keeps the transport local and uses the ZHA path already available in Home Assistant:

- learn and send are handled by the confirmed Zosung control cluster;
- the learned code is read from the backend ZHA device object;
- saved commands live in Home Assistant storage instead of volatile device attributes;
- services make the workflow available to the UI, automations, scripts, and agents.

## Non-Goals

The current architecture intentionally does not use:

- Tuya Cloud or Smart Life as the runtime;
- Zigbee2MQTT transport;
- SmartIR as the sender;
- Home Assistant helper entities as primary storage;
- Home Assistant core patches or ZHA monkey patching;
- a public IR code database.

SmartIR-compatible export and additional transmitter transports may be considered later, but they are not required for the current ZHA command workflow.

## Repository Layout

```text
custom_components/ir_learning_hub/
	__init__.py              # integration setup, services, frontend paths
	brand/                   # integration brand assets
	config_flow.py           # setup flow and ZHA transmitter discovery
	const.py                 # constants and service names
	device_profiles.py       # supported transmitter profile definitions
	errors.py                # localized integration error type
	icon.png                 # local Home Assistant integration icon
	sensor.py                # diagnostic status sensor platform
	services.yaml            # service field structure for Home Assistant
	status.py                # in-memory status model
	storage.py               # Store-backed command registry
	strings.json             # English source strings for HA translations
	translations/            # backend translations
	zha_adapter.py           # ZHA learn/read/send adapter
	www/ir-learning-hub-card.js

brand/                      # HACS repository icon assets
hacs.json

docs/
	ARCHITECTURE.md
	INSTALLATION.md
	SERVICES.md
	TROUBLESHOOTING.md
	ROADMAP.md
	ТЗ Native ZHA IR Learning Hub.md
```

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Services](docs/SERVICES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Roadmap](docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Current Russian technical specification](docs/ТЗ%20Native%20ZHA%20IR%20Learning%20Hub.md)

## Development Notes

The integration keeps ZHA transport logic in `zha_adapter.py`, registry logic in `storage.py`, setup logic in `config_flow.py`, and user workflow logic in the Lovelace card. The UI should call integration services and should not reimplement ZHA reads or Zigbee cluster traversal.

When publishing a release, keep `manifest.json`, the Lovelace card version, README examples, installation docs, changelog, the git tag, and the GitHub Release in sync. HACS uses the release/tag and manifest version to decide what users see.

## License

No license file is currently included. Until a license is added, this repository is not licensed for redistribution or reuse by default.
