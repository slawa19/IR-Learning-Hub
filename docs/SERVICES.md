# Services

IR Learning Hub exposes Home Assistant services under the `ir_learning_hub` domain. Services are the stable API for the Lovelace card, automations, scripts, and external agents.

Services that return data require Home Assistant service response data support.

## ID Rules

The registry uses stable IDs for automation-safe references:

```text
location_id:   [a-z0-9_]+
ir_device_id:  [a-z0-9_]+
command_id:    [a-z0-9_]+
```

Use display names for human-readable labels. Do not use spaces, punctuation, or non-ASCII characters in IDs.

## Learning and Sending

### `ir_learning_hub.learn`

Starts IR learning mode on the configured transmitter.

```yaml
timeout: 60
```

Returns:

```yaml
status: learn_started
```

The implementation may reassert learn mode during the timeout window because the TS1201 can leave learning mode before a long timeout expires.

### `ir_learning_hub.read_last_code`

Reads the last learned code from ZHA attribute `0`.

```yaml
{}
```

Returns response data:

```yaml
code: "<base64-code>"
```

If the volatile attribute is empty, the service raises `code_empty`.

### `ir_learning_hub.learn_and_read`

Starts learning and polls until a new learned code appears.

```yaml
timeout: 60
poll_interval: 1
```

Returns response data:

```yaml
code: "<base64-code>"
```

Polling is asynchronous and must not block the Home Assistant event loop. If no new code is found before timeout, the service raises `learn_timeout`.

### `ir_learning_hub.test_code`

Sends a raw code without saving it.

```yaml
code: "<base64-code>"
```

Returns:

```yaml
status: dispatched_unconfirmed
delivery_confirmed: false
request_id: "<request-id>"
transmitter_id: "<transmitter-id>"
queue_wait_ms: 0
command_age_ms: 0
queue_depth: 1
```

This means the command was handed to the ZHA send path. Physical IR delivery to
the target receiver is not confirmed.

### `ir_learning_hub.generate_code`

Generates a sendable `zosung_base64` code from protocol parameters.

Currently supported protocol:

```text
sony_sirc
```

Example Sony receiver power toggle:

```yaml
protocol: sony_sirc
command: 21
device: 16
bits: "12"
repeats: 3
```

Returns response data:

```yaml
code: "<base64-code>"
format: zosung_base64
carrier_frequency: 40000
source:
  type: protocol
  protocol: sony_sirc
  carrier_frequency: 40000
  params:
    command: 21
    device: 16
    bits: 12
    extended: 0
    repeats: 3
    frame_period_us: 45000
```

Use the returned `code` with `test_code` first. If the target device responds,
save it with `save_command`.

### `ir_learning_hub.save_command`

Saves or replaces a command in the registry.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
code: "<base64-code>"
verified: true
source:
  type: protocol
  protocol: sony_sirc
  carrier_frequency: 40000
  params:
    command: 21
    device: 16
    bits: 12
    extended: 0
    repeats: 3
    frame_period_us: 45000
```

Returns:

```yaml
status: saved
```

This service is an upsert. If the command already exists, the stored code, name, format, verified flag, and update timestamp are replaced.

If the existing command has an `icon`, relearning or saving a replacement code preserves that icon.

`source` is optional provenance for generated or imported commands. It is stored
for display, export, and future regeneration. It is not used when sending; the
runtime still sends the stored opaque `code`.

### `ir_learning_hub.update_command`

Updates a saved command's display metadata and/or semantic role without
relearning or replacing its IR code.

At least one of `name`, `icon`, or `feature` is required.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Tray Open/Close
icon: mdi:eject
feature: play
```

`feature` assigns the command's **semantic role** from the closed vocabulary
below. It is what `media_player`/`switch` capabilities are inferred from, so it
must be set for those entities to expose play/pause/source/etc. — the
`command_id` text is never interpreted. Use an empty string to clear the role.

```text
power_on  power_off  power_toggle
play  pause  play_pause_toggle  stop  next  previous  fast_forward  rewind
volume_up  volume_down  mute  unmute  mute_toggle
source
```

Mute roles are intentionally distinct:

- `mute` is a discrete mute-on command.
- `unmute` is a discrete mute-off command.
- `mute_toggle` is a toggle; Home Assistant state is assumed because the receiver
  does not report feedback.

Every command with `feature: source` becomes a selectable input; its display
`name` is the label shown in the media player's `source_list`.

Use an empty icon string to clear the stored icon:

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
icon: ""
```

Returns:

```yaml
status: saved
```

Icons must be Material Design icon names such as `mdi:play`, `mdi:power`, or `mdi:eject`.

### `ir_learning_hub.send_command`

Sends a saved command.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
```

Returns:

```yaml
status: dispatched_unconfirmed
delivery_confirmed: false
request_id: "<request-id>"
transmitter_id: "<transmitter-id>"
queue_wait_ms: 0
command_age_ms: 0
queue_depth: 1
```

This means the command was handed to the ZHA send path. Physical IR delivery to
the target receiver is not confirmed.

## Native Entities

Registry IR devices are exposed as native Home Assistant entities, selected by
the device's `preferred_domain` (and capabilities):

- `remote` — generic devices and the raw-passthrough escape hatch;
- `media_player` — AV devices; features and `source_list` come from each
  command's `feature` role;
- `switch` — pure on/off devices.

### Remote

```yaml
service: remote.send_command
target:
  entity_id: remote.living_room_tv
data:
  command: power_toggle
```

`command` must be a stored `command_id`. `remote.send_command` is a raw
passthrough — it uses the literal stored id, not the display label.

### Media player

Use the standard `media_player.*` services. Capabilities depend on which command
`feature` roles exist on the device (e.g. `play` → PLAY, `volume_up`/`down` →
VOLUME_STEP, any `source` → SELECT_SOURCE). `media_player.select_source` takes a
**source label** (the `name` of a `feature: source` command):

```yaml
service: media_player.select_source
target:
  entity_id: media_player.cabinet_sony_receiver
data:
  source: "Tuner / FM-AM"
```

Power semantics are honest: with only `power_toggle` the player is
`assumed_state` and cannot guarantee true on/off; with no power command it does
not advertise turn on/off.

### General

All consumer entities send through the Home Assistant infrared helper and the IR
Learning Hub emitter entity. They do not call ZHA directly. State is assumed
because IR has no feedback channel.

## Registry Management

### `ir_learning_hub.list_commands`

Returns the saved registry.

```yaml
{}
```

Example response:

```yaml
transmitters:
  - key: b0e8e8fffe16ef35
    ieee: "b0:e8:e8:ff:fe:16:ef:35"
    name: IR transmitter b0:e8:e8:ff:fe:16:ef:35
    enabled: true
locations:
  cabinet:
    name: Cabinet
    devices:
      cd_player:
        name: CD Player
        type: generic
        preferred_domain: remote
        transmitter_id: b0e8e8fffe16ef35
        commands:
          open_close:
            name: Open/Close
            icon: mdi:eject
            feature: play
            code: "<base64-code>"
            format: zosung_base64
            verified: true
            source:
              type: protocol
              protocol: sony_sirc
            updated_at: "2026-06-09T16:42:00+00:00"
```

The response includes a sanitized `transmitters` list so configured emitters
(and any orphaned records) are observable.

### `ir_learning_hub.add_location`

```yaml
location_id: cabinet
name: Cabinet
```

### `ir_learning_hub.add_device`

```yaml
location_id: cabinet
ir_device_id: cd_player
name: CD Player
type: generic
preferred_domain: remote
transmitter_id: "0011223344556677"
```

`preferred_domain` may be `auto`, `media_player`, `remote`, or `switch` — all are
implemented. `auto` picks a domain from `type` and inferred capabilities;
`switch` is only honored for pure on/off devices.

`transmitter_id` selects the emitter for this device when more than one
transmitter is configured. It is normalized and validated on write (accepts the
canonical key, an IEEE with colons, or the emitter `entity_id`); an unknown value
is rejected. Omit it with a single transmitter.

### `ir_learning_hub.update_device`

Updates a registry IR device without changing its commands.

At least one metadata field is required:

```yaml
location_id: cabinet
ir_device_id: cd_player
name: CD Transport
type: generic
preferred_domain: remote
transmitter_id: "0011223344556677"
```

Returns:

```yaml
status: saved
```

Use an empty `transmitter_id` to clear the stored transmitter assignment.

### `ir_learning_hub.add_command`

Creates an empty command placeholder. Accepts an optional `feature` role.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
feature: play
```

`save_command` also accepts an optional `feature` (see `update_command` for the
role vocabulary).

### `ir_learning_hub.rename_location`

```yaml
location_id: cabinet
name: Listening Room Cabinet
```

### `ir_learning_hub.rename_device`

```yaml
location_id: cabinet
ir_device_id: cd_player
name: CD Transport
```

### `ir_learning_hub.rename_command`

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Tray Open/Close
```

`rename_command` is kept for compatibility and simple scripts. New UI flows use `update_command` when changing command display metadata.

### `ir_learning_hub.delete_location`

Deletes a location and all nested devices and commands.

```yaml
location_id: cabinet
confirm: true
```

### `ir_learning_hub.delete_device`

Deletes an IR device and all nested commands.

```yaml
location_id: cabinet
ir_device_id: cd_player
confirm: true
```

### `ir_learning_hub.delete_command`

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
```

## Transmitters and `transmitter_id`

The integration is a single hub config entry; each physical transmitter is a
config **subentry** with its own `infrared` emitter entity. Add or remove
transmitters from the hub in Settings → Devices & Services.

Transmitter-facing services (`learn`, `send_command`, `test_code`, etc.) accept
an optional `transmitter_id`. Omit it when only one transmitter is enabled. With
multiple transmitters, pass a reference that resolves to a transmitter — the
canonical key (IEEE without colons, lowercased), an IEEE with colons, or the
emitter `entity_id`. Per-device routing is set with `add_device`/`update_device`
`transmitter_id`.

## Error Codes

Common error codes include:

```text
transmitter_not_configured
transmitter_required
transmitter_unavailable
zha_unavailable
zha_device_not_found
cluster_not_found
learn_failed
learn_timeout
code_empty
code_generation_failed
send_failed
command_expired
queue_full
dispatcher_stopped
command_not_found
storage_error
unknown_profile
unexpected_error
```

UI code should display the stable error code separately from the human-readable message.
