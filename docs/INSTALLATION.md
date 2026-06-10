# Installation

This document describes how to install IR Learning Hub as a local Home Assistant custom integration.

## Requirements

- Home Assistant with ZHA enabled.
- A paired Tuya TS1201 / MOES UFO-R11 IR blaster.
- The ZHA quirk `zhaquirks.tuya.ts1201.ZosungIRBlaster` active for the device.
- File access to the Home Assistant configuration directory.

The currently confirmed device profile uses:

```text
Endpoint: 1
IR control cluster: 0xE004 / 57348
Learn command: 1
Send command: 2
Learned-code attribute: 0
```

## Manual Installation

Copy or mount the integration directory into Home Assistant:

```text
<ha_config>/custom_components/ir_learning_hub
```

The resulting path should contain `manifest.json`:

```text
<ha_config>/custom_components/ir_learning_hub/manifest.json
```

The local integration icon is expected at:

```text
<ha_config>/custom_components/ir_learning_hub/icon.png
```

Restart Home Assistant after copying the files.

## HACS Installation

Add this repository as a HACS custom repository:

```text
https://github.com/slawa19/IR-Learning-Hub
```

Use category `Integration`.

HACS should install a GitHub release/tag, not a raw commit SHA. The release version must match the integration version in `manifest.json`. For example, release `0.1.0` must contain:

```json
"version": "0.1.0"
```

If HACS shows an error such as `The version fb1af13 for this integration can not be used with HACS`, create or select a release/tag version instead of installing that commit hash.

## Add the Integration

1. Open Home Assistant.
2. Go to `Settings -> Devices & services`.
3. Select `Add integration`.
4. Search for `IR Learning Hub`.
5. Select the detected ZHA IR transmitter.

The config flow scans Home Assistant's ZHA device registry and lists devices that expose the supported IR control cluster. The saved configuration uses the selected device's own IEEE, endpoint, and cluster values.

If your transmitter is not listed, choose manual setup and enter the values from the ZHA device details. The confirmed TS1201 / Zosung profile uses:

```text
Profile: ts1201_zosung
Endpoint: 1
Cluster: 57348
Learn timeout: 60
Learn reassert interval: 8
```

## Add the Lovelace Card

The integration serves the bundled card at:

```text
/ir_learning_hub/ir-learning-hub-card.js
```

Add it as a Lovelace resource:

```yaml
url: /ir_learning_hub/ir-learning-hub-card.js?v=1
type: module
```

Then add a card:

```yaml
type: custom:ir-learning-hub-card
title: IR Learning Hub
status_entity: sensor.ir_learning_hub_status
timeout: 60
poll_interval: 2
```

## First Validation

Use Developer Tools to call `ir_learning_hub.learn_and_read` with response data enabled.

Example data:

```yaml
timeout: 60
poll_interval: 1
```

After starting the service call, point the physical IR remote at the TS1201 and press a button. A successful call returns:

```yaml
code: "<base64-code>"
```

Then call `ir_learning_hub.test_code` with the returned code. If the controlled device reacts, save the command with `ir_learning_hub.save_command`.

## Updating

1. Replace the files under `custom_components/ir_learning_hub`.
2. Restart Home Assistant.
3. Refresh the browser cache if the Lovelace card changed.
4. Bump the card resource query string if needed, for example `?v=2`.

## Uninstalling

1. Remove the integration entry from `Settings -> Devices & services`.
2. Remove `custom_components/ir_learning_hub` from the Home Assistant configuration directory.
3. Restart Home Assistant.

Saved registry data lives in Home Assistant `.storage`. Back it up before deleting integration storage manually.
