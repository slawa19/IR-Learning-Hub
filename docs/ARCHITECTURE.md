# Architecture

IR Learning Hub is a Home Assistant custom integration that wraps native ZHA operations with a purpose-built IR learning and command registry workflow.

## Design Goals

- Keep IR learning and replay local to Home Assistant.
- Use ZHA for the confirmed TS1201 / Zosung transport path.
- Expose a stable service API for UI, automations, scripts, and agents.
- Expose learned IR devices as native Home Assistant entities where possible.
- Store command registry data in Home Assistant storage instead of helper entities.
- Keep the Lovelace card thin: it should call integration services, not ZHA internals.
- Avoid Home Assistant core patches and monkey patching.

## High-Level Flow

```text
Tuya TS1201 / MOES UFO-R11
  -> ZHA + zhaquirks.tuya.ts1201.ZosungIRBlaster
  -> IR Learning Hub ZHA adapter
  -> IR Learning Hub infrared emitter entity (one per transmitter subentry)
  -> consumer entities: remote / media_player / switch  (resolve command -> code)
  -> Lovelace card / HA services / Assist / automations / scripts / agents
```

## Config-entry model (hub + subentries)

The integration is a **single hub config entry**. Each physical transmitter is a
**config subentry** of type `transmitter`. This is the canonical Home Assistant
"hub + sub-devices" shape:

- the hub entry owns the store, services, status sensor, and the consumer
  platforms (`remote` / `media_player` / `switch`) plus their virtual devices;
- each `transmitter` subentry owns one `infrared` emitter entity and its device.

Installs from before `0.3.0` (one config entry per transmitter) are migrated once
into this shape at component startup; the registry store is never rewritten.

## Main Components

### `config_flow.py`

Creates the single hub config entry and seeds its first `transmitter` subentry
(ZHA discovery, with manual setup as a fallback). The current profile is
`ts1201_zosung`. `async_get_supported_subentry_types` exposes the
`IRLearningHubTransmitterSubentryFlow` (`user` + `reconfigure` steps) for adding
or editing transmitters; duplicate transmitters are blocked by a canonical
subentry `unique_id`. Each subentry stores transmitter connection parameters
(IEEE, endpoint, cluster, profile, learn timeout, reassert interval).

### `zha_adapter.py`

Owns transport-level ZHA behavior:

- resolves the Home Assistant ZHA device registry ID from IEEE;
- sends learn and transmit commands through `zha.issue_zigbee_cluster_command`;
- reads the last learned code through `async_get_zha_device_proxy` and the nested zigpy cluster object;
- maps ZHA failures to integration error codes.

`zha_adapter.py` is transport-only. Consumer entities must not import it.
Entity sends go through the Home Assistant `infrared` helper and the integration
emitter entity.

### `infrared.py`

Exposes one `InfraredEmitterEntity` per `transmitter` subentry (added with that
subentry's `config_subentry_id`).

The emitter represents the physical transmitter, wraps the existing
`ZHAAdapter`, and accepts opaque `ZosungCommand` payloads. It is the only entity
layer object that sends through ZHA.

### `ir_command.py`

Defines `ZosungCommand`, a small `infrared_protocols.commands.Command`
subclass carrying the stored opaque `zosung_base64` code. `get_raw_timings()` is
not available for this opaque v1 command; full raw-timing interoperability is a
future decoder task.

### `capabilities.py`

Pure capability inference from each command's explicit **`feature`** role (a
closed vocabulary: `power_on/off/toggle`, `play`, `pause`, `play_pause_toggle`,
`stop`, `next`, `previous`, `fast_forward`, `rewind`, `volume_up/down`,
`mute/unmute/mute_toggle`, `source`). Inference reads `feature`, never the
free-text `command_id`. The legacy command-id vocabulary now only seeds
`feature` during migration.

### `registry_runtime.py`

Pure Python registry projection logic. Converts store data into desired entity
specs (domain selection by `preferred_domain`/`type` + capabilities, and a
`feature -> command_id` map) without Home Assistant imports, so projection and
dynamic lifecycle decisions can be unit tested.

### `consumer.py`

Shared base for all consumer platforms: the `ConsumerEntityManager` (dynamic
add/update/remove with a trailing-edge reconcile so bursts of registry changes
are never dropped, plus entity/device registry cleanup), the
`RegistryBackedConsumerEntity` mixin (DeviceInfo with `via_device` to the
emitter, assumed state), the send helpers, and transmitter resolution. Consumer
entities call `infrared.async_send_command(hass, emitter_entity_id, command,
context=...)` and never touch ZHA or the adapter directly.

### `remote.py`, `media_player.py`, `switch.py`

Consumer platforms built on `consumer.py`:

- `remote.py` — `remote` entities; `remote.send_command` resolves literal
  `command_id` values (raw passthrough escape hatch).
- `media_player.py` — `media_player` entities; features and `source_list` are
  built from inferred capabilities, and service calls resolve commands by
  `feature` (`media_player.select_source` maps the source label back to its
  command). Honest power semantics: no fake `OFF` when the device has no power
  command.
- `switch.py` — `switch` entities for pure on/off devices.

All resolve commands strictly (by `feature` for media_player/switch, by literal
id for `remote.send_command`), wrap the stored code in `ZosungCommand`, and send
through the emitter. State is assumed because IR has no feedback path.

### `transmitter_identity.py`

Normalizes any transmitter reference (canonical key, IEEE, or emitter
`entity_id`) to the single canonical key (`normalize_ieee(ieee)`). Used by
write-path validation and migration so `device.transmitter_id` is always stored
as the canonical key.

### `storage_migration.py`

Pure storage migrations: v1→v2 (entity-projection fields), v2→v3 (seed command
`feature` from canonical legacy ids), v3→v4 (canonicalize stored
`transmitter_id`).

### `storage.py`

Owns persistent registry state using Home Assistant `Store`.

The current store (schema v4) contains transmitter metadata and user command
registry data:

```json
{
  "version": 4,
  "transmitters": {},
  "locations": {}
}
```

Locations contain IR devices, and IR devices contain commands. Devices may also
store `preferred_domain` and a canonical `transmitter_id` for entity projection
and multi-transmitter routing. Commands may carry an explicit `feature` role
(consumed by capability inference). Saved command codes are treated as opaque
`zosung_base64` payloads by the send path.

The store is independent of config entries/subentries — it is keyed by the
canonical transmitter id and survives entry/subentry changes. On setup the
integration reconciles stored transmitter records against existing subentries
and drops orphans.

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

Component-level `async_setup` runs the one-time legacy→hub migration. The hub
entry's `async_setup_entry` initializes runtime state (store, status, adapter),
registers services, upserts each `transmitter` subentry into the store, registers
emitter devices, reconciles orphaned transmitters, serves the bundled card, and
forwards **all** platforms (`sensor`, `infrared`, `remote`, `media_player`,
`switch`). A subentry-change update listener reloads the hub so emitters track
added/removed transmitters.

There is no owner-election: consumer platforms always live on the single hub
entry, and emitters live on their transmitter subentries. The earlier
owner-election/lifecycle machinery was removed by the hub+subentries restructure.

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

## Entity Boundary

The entity-first path is:

```text
remote / media_player / switch entity   (resolve feature or command_id -> stored code)
  -> Home Assistant infrared helper
     -> IR Learning Hub emitter entity
        -> ZHAAdapter
           -> ZHA / TS1201
```

`media_player`/`switch` resolve commands by their canonical `feature` role;
`remote.send_command` resolves literal registry `command_id` values. Display
labels are never used for command resolution (except the media_player source
label, which maps back to its `source` command).

## Deferred Architecture

The following are intentionally outside the current MVP:

- SmartIR runtime;
- SmartIR export;
- Zigbee2MQTT transport;
- Tuya Cloud transport;
- automatic IR code database lookup;
- bundled public IR code database;
- climate entities.
