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
status: sent
```

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

Updates a saved command's display metadata without relearning or replacing its IR code.

At least one of `name` or `icon` is required.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Tray Open/Close
icon: mdi:eject
```

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
status: sent
```

## Native Remote Entities

Starting with `v0.2.0`, registry IR devices are also exposed as Home Assistant
`remote` entities.

Use Home Assistant's normal remote services:

```yaml
service: remote.send_command
target:
  entity_id: remote.living_room_tv
data:
  command: power_toggle
```

`command` must be a stored `command_id`, such as `power_toggle`,
`volume_up`, or `source_hdmi_1`. Display names are not used for command
resolution.

The entity send path goes through the Home Assistant infrared helper and the IR
Learning Hub emitter entity. It does not call ZHA directly from the consumer
entity.

Remote power state is assumed. With only `power_toggle`, Home Assistant cannot
know whether the physical device is truly on or off after manual changes.

## Registry Management

### `ir_learning_hub.list_commands`

Returns the saved registry.

```yaml
{}
```

Example response:

```yaml
locations:
  cabinet:
    name: Cabinet
    devices:
      cd_player:
        name: CD Player
        type: generic
        commands:
          open_close:
            name: Open/Close
            icon: mdi:eject
            code: "<base64-code>"
            format: zosung_base64
            verified: true
            source:
              type: protocol
              protocol: sony_sirc
            updated_at: "2026-06-09T16:42:00+00:00"
```

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

`preferred_domain` may be `auto`, `media_player`, `remote`, or `switch`.
In `v0.2.0`, `remote` entities are implemented; `media_player` and `switch`
projection are planned follow-ups.

`transmitter_id` selects the emitter used for this virtual IR device when more
than one transmitter is configured.

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

Creates an empty command placeholder.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
```

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

## Optional Transmitter ID

Most services accept an optional `transmitter_id`. Omit it when only one transmitter is enabled.

If multiple transmitters are enabled, pass the normalized transmitter ID. The current storage model normalizes IEEE addresses by removing colons and lowercasing the result.

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
command_not_found
storage_error
unknown_profile
unexpected_error
```

UI code should display the stable error code separately from the human-readable message.
