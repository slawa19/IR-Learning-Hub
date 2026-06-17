# Installation

This document describes how to install IR Learning Hub as a local Home Assistant custom integration.

## Requirements

- Home Assistant 2026.6.0 or newer with ZHA enabled.
- A paired Tuya TS1201 / MOES UFO-R11 IR blaster.
- The ZHA quirk `zhaquirks.tuya.ts1201.ZosungIRBlaster` active for the device.
- File access to the Home Assistant configuration directory only for manual installation.

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

The card's header icon is served from the integration folder. The integration
uses `icon.png` at the integration root if it exists, otherwise it falls back to
`brand/icon.png`:

```text
<ha_config>/custom_components/ir_learning_hub/icon.png
# fallback:
<ha_config>/custom_components/ir_learning_hub/brand/icon.png
```

The `brand/` icons are also used by Home Assistant 2026.3+ as local brand
images. HACS repository listing assets are kept separately in the repository
root under `brand/`.

Restart Home Assistant after copying the files.

## HACS Installation

Add this repository as a HACS custom repository:

```text
https://github.com/slawa19/IR-Learning-Hub
```

Use category `Integration`.

Install the latest available release, restart Home Assistant, then add the integration from `Settings -> Devices & services`.

For the entity-first release, install `v0.3.0` or newer. The integration manifest should contain:

```json
{ "version": "0.3.0" }
```

## Add the Integration

1. Open Home Assistant.
2. Go to `Settings -> Devices & services`.
3. Select `Add integration`.
4. Search for `IR Learning Hub`.
5. Select the detected ZHA IR transmitter. This creates the hub and its first transmitter.

The config flow scans Home Assistant's ZHA device registry and lists devices that expose the supported IR control cluster. The saved configuration uses the selected device's own IEEE, endpoint, and cluster values. The integration is created as a single hub; add further transmitters later from the hub's "Add transmitter" subentry flow.

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
url: /ir_learning_hub/ir-learning-hub-card.js
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

You can also validate through the Lovelace card:

1. Create a location and device.
2. Add a command.
3. Complete the record, test, and save wizard.
4. Use the command tile to replay the saved code.

## Updating

### HACS update to `v0.3.0`

1. In HACS, open `IR Learning Hub`.
2. Install release `v0.3.0` or newer.
3. Restart Home Assistant.
4. Reload the dashboard in the browser.
5. Open `Settings -> Devices & services -> Entities` and verify the new entities.

If HACS still shows an older version, reload HACS data and check for the latest release again.

### Manual update to `v0.3.0`

1. Download or checkout tag `v0.3.0`.
2. Replace the files under:

   ```text
   <ha_config>/custom_components/ir_learning_hub
   ```

3. Confirm the installed manifest says:

   ```json
   { "version": "0.3.0" }
   ```

4. Restart Home Assistant.
5. Reload the dashboard in the browser.

### Post-update validation

Updating to `v0.3.0` runs a one-time migration that reshapes the old
one-entry-per-transmitter setup into a single hub entry with transmitter
subentries. Learned commands are preserved (the registry store is untouched).
After restart, check:

1. The integration shows one `IR Learning Hub` entry with a transmitter subentry.
2. The existing status sensor still exists:

   ```text
   sensor.ir_learning_hub_status
   ```

3. Each transmitter has a native `infrared` emitter entity.
4. Each registry IR device has its consumer entity (`remote` / `media_player` / `switch`).
5. Existing services still work, especially:

   ```text
   ir_learning_hub.send_command
   ir_learning_hub.test_code
   ```

5. If you use Assist or an LLM assistant, expose the new `remote` entities in:

   ```text
   Settings -> Voice assistants -> Expose
   ```

The integration does not force Assist exposure. Home Assistant's exposure policy stays in control.

## Uninstalling

1. Remove the integration entry from `Settings -> Devices & services`.
2. Remove `custom_components/ir_learning_hub` from the Home Assistant configuration directory.
3. Restart Home Assistant.

Saved registry data lives in Home Assistant `.storage`. Back it up before deleting integration storage manually.
