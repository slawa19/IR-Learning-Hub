# IR Learning Hub

Local Home Assistant custom integration for learning, storing, and sending IR commands through a ZHA-connected Zigbee IR remote.

The project specification is maintained in [docs/ТЗ IR Learning Hub.md](docs/ТЗ%20IR%20Learning%20Hub.md).

## Planned MVP

- One confirmed ZHA IR transmitter.
- Generic IR devices.
- Registry storage through Home Assistant `.storage`.
- Services for learn, test, save, and send flows.
- Status sensor for diagnostics.
- Basic Lovelace card for learning and sending commands.

## First development gate

Before backend implementation, phase 0 must confirm the real IR remote supports learning, reading the learned code, sending the saved code, and sending again after a Home Assistant restart.