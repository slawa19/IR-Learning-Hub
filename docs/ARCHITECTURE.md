# Architecture

IR Learning Hub is a Home Assistant custom integration that wraps native ZHA operations with a purpose-built IR learning and command registry workflow.

## Design Goals

- Keep IR learning and replay local to Home Assistant.
- Use ZHA for the confirmed TS1201 / Zosung transport path.
- Expose a stable service API for UI, automations, scripts, and agents.
- Store command registry data in Home Assistant storage instead of helper entities.
- Keep the Lovelace card thin: it should call integration services, not ZHA internals.
- Avoid Home Assistant core patches and monkey patching.

## High-Level Flow

```text
Tuya TS1201 / MOES UFO-R11
  -> ZHA + zhaquirks.tuya.ts1201.ZosungIRBlaster
  -> IR Learning Hub ZHA adapter
  -> IR Learning Hub services and Store-backed registry
  -> Lovelace card / HA services / automations / scripts / agents
```

## Main Components

### `config_flow.py`

Creates a config entry for a ZHA IR transmitter. The current profile is `ts1201_zosung`.

The config entry stores transmitter connection parameters such as IEEE, endpoint, cluster, profile, learn timeout, and learn reassert interval.

### `zha_adapter.py`

Owns transport-level ZHA behavior:

- resolves the Home Assistant ZHA device registry ID from IEEE;
- sends learn and transmit commands through `zha.issue_zigbee_cluster_command`;
- reads the last learned code through `async_get_zha_device_proxy` and the nested zigpy cluster object;
- maps ZHA failures to integration error codes.

### `storage.py`

Owns persistent registry state using Home Assistant `Store`.

The current store contains transmitter metadata and user command registry data:

```json
{
  "version": 1,
  "transmitters": {},
  "locations": {}
}
```

Locations contain IR devices, and IR devices contain commands. Saved command codes are treated as opaque `zosung_base64` payloads by the send path.

Commands may also contain optional display metadata such as `icon` and optional
`source` provenance for generated/imported commands. This metadata is
independent from the stored IR code and is not used by the ZHA send path.

### `ir_formats/`

Pure Python IR conversion helpers with no Home Assistant imports.

The current pipeline is:

```text
protocol source -> normalized raw timings -> zosung_base64 -> existing send path
```

The implemented protocol source is Sony SIRC. It expands protocol repeats and
inter-frame gaps into the raw timing list before Zosung encoding, because the
TS1201 sends one continuous timing payload per command.

### `__init__.py`

Initializes runtime state, registers services, forwards the sensor platform, serves the bundled card, and coordinates status updates.

### `sensor.py` and `status.py`

Expose a diagnostic status sensor. The status sensor is not the primary API; services are the primary API.

### `www/ir-learning-hub-card.js`

Provides the first Lovelace card. The card should call `ir_learning_hub.*` services only.

## ZHA Details

The confirmed TS1201 path uses:

```text
Endpoint: 1
Cluster: 0xE004 / 57348
Learn command: 1
Send command: 2
Learned-code attribute: 0
```

Sending uses the native Home Assistant ZHA service `zha.issue_zigbee_cluster_command`.

Reading uses backend access to the ZHA device proxy and real zigpy cluster:

```python
zha_device_proxy = async_get_zha_device_proxy(hass, device_registry_id)
cluster = ... # endpoint 1, in cluster 0xE004
attrs, failed = await cluster.read_attributes([0])
```

The exact wrapper depth can vary across Home Assistant versions, so `zha_adapter.py` walks nested `.device` objects until it finds a matching endpoint and cluster.

## Learning Model

`learn_and_read` stores the previous attribute value, starts learn mode, and then polls asynchronously until a new non-empty value appears or timeout expires.

The service uses `asyncio.sleep(...)` between reads. Synchronous sleeps and busy waits are not acceptable inside Home Assistant service handlers.

The implementation may reassert learn mode during the timeout window. This compensates for TS1201 behavior where the physical device can leave learning mode before a long user-facing timeout has elapsed.

## Storage Model

Registry IDs are stable automation identifiers and must match `[a-z0-9_]+`.

Display names are user-facing labels and may be changed without changing IDs.

Saved commands are upserted by the tuple:

```text
location_id / ir_device_id / command_id
```

Command payloads are opaque strings at runtime. The optional converter layer may
generate or decode payloads before they are saved, but `send_command` always
sends the stored `code` as-is.

## UI Boundary

The Lovelace card must not:

- call ZHA services directly;
- read ZHA WebSocket endpoints directly;
- traverse zigpy or ZHA device objects;
- implement its own storage model.

The card should use integration services and response data only.

The card owns user-facing workflows that do not require ZHA access:

- location, device, and command menus;
- inline rename actions;
- command icon selection;
- device-profile export and import;
- a compact diagnostic status indicator.

Profile export/import is a UI-level portability helper. The exported JSON contains one IR device's commands and is imported by calling existing integration services, primarily `save_command` and `update_command`. Imported commands may include `source` provenance.

## Deferred Architecture

The following are intentionally outside the current MVP:

- SmartIR runtime;
- SmartIR export;
- Zigbee2MQTT transport;
- Tuya Cloud transport;
- multiple active transmitters in one UI workflow;
- automatic IR code database lookup;
- bundled public IR code database;
- climate entities.
