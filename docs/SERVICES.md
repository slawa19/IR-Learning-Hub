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

### `ir_learning_hub.save_command`

Saves or replaces a command in the registry.

```yaml
location_id: cabinet
ir_device_id: cd_player
command_id: open_close
name: Open/Close
code: "<base64-code>"
verified: true
```

Returns:

```yaml
status: saved
```

This service is an upsert. If the command already exists, the stored code, name, format, verified flag, and update timestamp are replaced.

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
            code: "<base64-code>"
            format: zosung_base64
            verified: true
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
```

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
send_failed
command_not_found
storage_error
unknown_profile
unexpected_error
```

UI code should display the stable error code separately from the human-readable message.