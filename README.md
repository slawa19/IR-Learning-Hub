# IR Learning Hub

Local Home Assistant custom integration for learning, storing, and sending IR commands through a ZHA-connected Tuya TS1201 / MOES UFO-R11 IR blaster.

The main project specification is maintained in [docs/ТЗ Native ZHA IR Learning Hub.md](docs/ТЗ%20Native%20ZHA%20IR%20Learning%20Hub.md).

Earlier IR Learning Hub research notes are archived in [docs/archive/ТЗ IR Learning Hub - research archive.md](docs/archive/ТЗ%20IR%20Learning%20Hub%20-%20research%20archive.md).

## Planned MVP

- Select the confirmed ZHA TS1201 transmitter.
- Learn an IR command through native ZHA.
- Read the learned code from ZHA attribute `0`.
- Test the code through native ZHA send.
- Save commands into `.storage`.
- Send saved commands through Home Assistant services and UI.

## Important Scope

SmartIR is not required for the MVP. Native ZHA already covers learning, reading, and sending IR codes for the confirmed TS1201 device. SmartIR-compatible export can be added later if it becomes useful.