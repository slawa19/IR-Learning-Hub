# Troubleshooting

## `code_empty` after restart

This is expected for the TS1201. The last-learned-code attribute is volatile and can be empty after Home Assistant or device restart.

Saved commands are stored separately in Home Assistant storage and should still be available through `send_command`.

## `learn_timeout`

The integration did not observe a new non-empty code before timeout.

Check:

- the physical remote is pointed at the TS1201;
- the remote has working batteries;
- the TS1201 LED enters learning mode;
- `timeout` is long enough;
- `poll_interval` is not too large;
- the selected transmitter is the expected ZHA device.

Try `timeout: 60` and `poll_interval: 1` for validation.

## `zha_device_not_found`

The configured IEEE address could not be matched to a ZHA device registry entry.

Check:

- the TS1201 is paired with ZHA;
- the IEEE address in the config entry is correct;
- the device has not been removed and re-paired under a different address;
- ZHA is loaded before IR Learning Hub starts.

## `cluster_not_found`

The integration could not find the expected control cluster on the configured endpoint.

Check:

- the device is the supported TS1201 / MOES UFO-R11 profile;
- the active quirk is `zhaquirks.tuya.ts1201.ZosungIRBlaster`;
- endpoint is `1`;
- control cluster is `0xE004` / `57348`.

## `send_failed`

The ZHA send command failed or an empty code was sent.

Check:

- the saved command has a non-empty `code`;
- the TS1201 is online in ZHA;
- the target IR device is in range;
- the ZHA network is healthy.

## Command does not control the target device

A service call can succeed even if the target IR device does not react. ZHA can confirm that the command was sent to the IR blaster, but it cannot confirm that the IR receiver accepted it.

Try:

- relearning the command closer to the TS1201;
- testing the command before saving it as verified;
- moving the TS1201 for better IR line of sight;
- checking whether the original remote uses a long press or repeated frame behavior.

## Generated Sony code does not control the receiver

First confirm that normal learned commands work with the same TS1201 placement.

For Sony receivers, start with:

```yaml
protocol: sony_sirc
device: 16
bits: "12"
repeats: 3
```

If the receiver is configured for an alternate Sony AV mode, try:

```yaml
protocol: sony_sirc
device: 48
bits: "15"
repeats: 3
```

Use `generate_code`, then `test_code`, before saving a command as verified.

## Lovelace card does not load

Check:

- Home Assistant was restarted after installing the integration;
- the resource URL is `/ir_learning_hub/ir-learning-hub-card.js?v=11`;
- the resource type is `module`;
- the browser cache was refreshed;
- the file exists at `custom_components/ir_learning_hub/www/ir-learning-hub-card.js`.

The card logs its loaded version in the browser console:

```text
IR-LEARNING-HUB-CARD 0.1.11
```

If the console shows an older version, update the Lovelace resource query string and hard-refresh the browser.

## Export profile copy does not put JSON on the clipboard

The card first uses the browser Clipboard API and then falls back to copying from the export textarea. If neither path works, use the download button instead.

Check:

- the browser allows clipboard access for the Home Assistant site;
- the export textarea contains JSON;
- the card version in the browser console is current;
- another browser extension is not blocking clipboard writes.

## IDs are rejected

Registry IDs must match:

```text
[a-z0-9_]+
```

Use IDs such as `cabinet`, `cd_player`, and `open_close`. Put human-friendly labels in the `name` field.

## Enable Debug Logging

Add this to Home Assistant logging configuration when investigating ZHA or integration behavior:

```yaml
logger:
  default: info
  logs:
    custom_components.ir_learning_hub: debug
    zhaquirks.tuya.ts1201: debug
    zigpy: debug
```

Disable verbose Zigbee logging after troubleshooting because it can produce a large amount of output.
