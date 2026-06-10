# IR Learning Hub

IR Learning Hub is a local Home Assistant custom integration for learning, storing, testing, and replaying infrared commands through a ZHA-connected Tuya TS1201 / MOES UFO-R11 IR blaster.

The project is intentionally built around Home Assistant's native ZHA runtime. It does not require Tuya Cloud, Smart Life, Zigbee2MQTT, SmartIR, IR Wrapper, or helper-entity based storage for the main command path.

## The Problem

Many inexpensive Zigbee IR blasters can transmit infrared commands, but turning them into a maintainable Home Assistant command library is harder than it first appears. The Tuya TS1201 / MOES UFO-R11 exposes the required IR functionality through vendor-specific ZHA clusters and quirks, not through a polished end-user learning workflow.

For the confirmed TS1201 device, local ZHA access can start learning mode, read the last learned IR code from attribute `0`, and send that code back through the same control cluster. The technical challenge is that these capabilities are split across low-level ZHA service calls and backend cluster access:

- learning requires a vendor-specific ZHA cluster command;
- the learned code is exposed as a volatile attribute, not as a durable Home Assistant entity;
- the code must be captured before it disappears or becomes stale;
- users need stable command names, storage, testing, and replay from automations without manually copying base64 payloads between Developer Tools screens.

IR Learning Hub addresses that gap by providing a small local integration that owns the workflow end to end: learn an IR command, read the code from ZHA, test it, save it in Home Assistant storage, and expose replay through services and a Lovelace card.

## Alternatives Considered

Several approaches were evaluated before choosing the current native ZHA design.

### SmartIR runtime

SmartIR is useful when a supported controller backend can send codes for a device profile. It also defines a JSON format for device command libraries. However, SmartIR `v1.18.1` does not provide a ZHA / TS1201 controller backend for this IR blaster. Generating SmartIR-compatible JSON would not, by itself, make SmartIR able to transmit through the TS1201.

For that reason, SmartIR is not used as the MVP runtime. A future export feature may still generate SmartIR-like files for portability, but SmartIR does not control learning, storage, sending, or UI behavior in this project.

### Tuya Cloud and Smart Life

The TS1201 can be used through Tuya ecosystems, but the goal of this project is local Home Assistant control. Cloud-dependent operation would add external availability, privacy, account, and vendor API risks for a workflow that ZHA can already perform locally.

Tuya Cloud and Smart Life were rejected for the core architecture because they are unnecessary for the confirmed hardware path and do not satisfy the local-first requirement.

### Zigbee2MQTT

Zigbee2MQTT is a valid Zigbee stack for many installations, but this project targets Home Assistant systems already using ZHA. Requiring a migration from ZHA to Zigbee2MQTT would increase operational complexity and would not solve the main product problem: users still need a command registry, learning flow, testing flow, and Home Assistant service interface.

Zigbee2MQTT support can be reconsidered later as a separate transport adapter, but it is outside the current implementation.

### IR Wrapper and helper entities

IR Wrapper and Home Assistant helpers can be used to assemble manual workflows, but they are not a durable integration architecture. Storing codes in `input_text` helpers or scripts makes validation, migration, service responses, UI state, and command organization harder to maintain.

This project uses Home Assistant's `Store` API for structured registry data and exposes explicit services instead of relying on helper entities as the final storage model.

### Home Assistant core patches or monkey patching

Patching Home Assistant core or monkey-patching ZHA internals would make the project fragile across Home Assistant releases. The implementation instead uses public Home Assistant service calls for sending and the available ZHA device proxy / zigpy cluster path for reading the learned attribute.

## Why Native ZHA

Native ZHA was chosen because it is the shortest reliable path for the confirmed device:

- the TS1201 is already paired with ZHA;
- the active quirk exposes the required Zosung IR control behavior;
- learn and send are confirmed through cluster `0xE004` / `57348`;
- learned codes can be read from attribute `0` through backend ZHA access;
- Home Assistant services can expose the workflow to the UI, automations, scripts, and agents.

The result is a local, narrowly scoped integration that solves the missing product workflow without replacing the user's Zigbee stack.

## Current Status

This repository is an early-stage custom integration. MVP-0 backend access has been validated on Home Assistant OS with ZHA and a confirmed TS1201 / MOES UFO-R11 device:

- `learn_and_read` can start learning and return a new code from ZHA attribute `0x0000`.
- Backend ZHA access works through `async_get_zha_device_proxy(hass, device_registry_id)`.
- The real zigpy cluster is reachable through the nested ZHA device object.
- Saved commands survive a Home Assistant restart and can be sent again.

Known behavior: after a Home Assistant restart, `read_last_code` can return `code_empty` until a new IR button is learned. The TS1201's last-learned-code attribute is volatile; saved commands are stored separately and are not affected.

## Supported Hardware

The implementation is currently targeted at one confirmed profile:

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

Cluster `0xED00` / `60672` may also appear on the device, but the MVP uses cluster `0xE004` because learn and send are confirmed there.

## Features

- Config flow for a ZHA TS1201 transmitter.
- Native ZHA learn, read, test, and send operations.
- Async polling for `learn_and_read` without blocking the Home Assistant event loop.
- Structured command registry stored with Home Assistant `Store`.
- Stable IDs for locations, IR devices, and commands.
- Registry management services for create, rename, delete, list, save, and replay operations.
- Diagnostic status sensor.
- Bundled Lovelace card served from the integration.

## Repository Layout

```text
custom_components/ir_learning_hub/
	__init__.py              # integration setup and service registration
	config_flow.py           # transmitter setup flow
	const.py                 # constants and service names
	device_profiles.py       # supported transmitter profile definitions
	errors.py                # integration error type
	sensor.py                # diagnostic status sensor platform
	services.yaml            # Home Assistant service descriptions
	status.py                # in-memory status model
	storage.py               # Store-backed command registry
	zha_adapter.py           # ZHA learn/read/send adapter
	www/ir-learning-hub-card.js

docs/
	ARCHITECTURE.md
	INSTALLATION.md
	SERVICES.md
	TROUBLESHOOTING.md
	ROADMAP.md
	ТЗ Native ZHA IR Learning Hub.md
```

## Installation

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for detailed steps.

Short version:

1. Copy or mount `custom_components/ir_learning_hub` into your Home Assistant configuration directory:

	 ```text
	 <ha_config>/custom_components/ir_learning_hub
	 ```

2. Restart Home Assistant.
3. Add the integration from `Settings -> Devices & services -> Add integration -> IR Learning Hub`.
4. Configure the TS1201 IEEE address, endpoint, cluster, timeout, and profile.
5. Add the Lovelace card resource if you want to use the bundled UI:

	 ```yaml
	 url: /ir_learning_hub/ir-learning-hub-card.js?v=1
	 type: module
	 ```

## Basic Usage

The most direct learning flow is:

1. Call `ir_learning_hub.learn_and_read` with response data enabled.
2. Point the physical IR remote at the TS1201 and press the desired button.
3. Use the returned `code` with `ir_learning_hub.test_code`.
4. If the target device responds, save it with `ir_learning_hub.save_command` and `verified: true`.
5. Replay the saved command with `ir_learning_hub.send_command`.

Example service data for saving a command:

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
code: "<base64-code>"
verified: true
```

IDs must match `[a-z0-9_]+`. Display names can be human-readable strings.

For a complete service reference, see [docs/SERVICES.md](docs/SERVICES.md).

## Lovelace Card

The first local card is bundled at:

```text
custom_components/ir_learning_hub/www/ir-learning-hub-card.js
```

Example card configuration:

```yaml
type: custom:ir-learning-hub-card
title: IR Learning Hub
status_entity: sensor.ir_learning_hub_status
timeout: 60
poll_interval: 2
```

The card uses only `ir_learning_hub.*` services. It does not talk to ZHA directly.

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

The integration intentionally keeps ZHA transport logic in `zha_adapter.py`, storage logic in `storage.py`, and UI behavior in the Lovelace card. The UI should call integration services and should not reimplement ZHA reads or Zigbee cluster traversal.

Before publishing this repository publicly, update placeholder metadata in `manifest.json`, especially the documentation and issue tracker URLs.

## License

No license file is currently included. Until a license is added, this repository is not licensed for redistribution or reuse by default.
