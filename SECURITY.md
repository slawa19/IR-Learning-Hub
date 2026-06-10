# Security Policy

## Supported Versions

This project is pre-release. Security fixes are handled on the current main branch until versioned releases are established.

## Reporting a Vulnerability

If you discover a security issue, report it privately to the repository maintainer once contact details are published.

Until public security contact information exists, do not disclose sensitive details in public issues.

## Scope

Relevant security issues include:

- unsafe handling of Home Assistant service data;
- unintended exposure of stored IR payloads;
- path traversal or static file serving issues;
- privilege escalation through the Lovelace card or integration services;
- unsafe use of Home Assistant or ZHA internals.

Out of scope:

- physical access attacks against IR devices;
- generic Zigbee network compromise unrelated to this integration;
- cloud service issues, because the integration does not use cloud services for its runtime path.

## Data Handling

IR Learning Hub stores learned IR command payloads in Home Assistant storage. These payloads can control devices in IR range of the transmitter. Treat backups and `.storage` data as sensitive if IR commands can affect security-relevant equipment.

The integration does not require Tuya Cloud credentials, Smart Life credentials, or external API tokens.