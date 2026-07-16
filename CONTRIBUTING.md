# Contributing

Thank you for your interest in improving IR Learning Hub.

This project is currently focused on a narrow, confirmed Home Assistant + ZHA + TS1201 path. Contributions should preserve the local-first architecture and avoid adding cloud dependencies to the core workflow.

## Before Opening a Pull Request

Please make sure the change:

- keeps ZHA transport behavior inside `zha_adapter.py`;
- keeps registry persistence inside `storage.py`;
- exposes user workflows through `ir_learning_hub.*` services;
- does not make the Lovelace card call ZHA directly;
- does not introduce Tuya Cloud, Smart Life, or SmartIR as a required runtime dependency;
- keeps command IDs stable and automation-safe.

## Development Setup

1. Clone the repository.
2. Copy or mount `custom_components/ir_learning_hub` into a Home Assistant development or test instance.
3. Restart Home Assistant.
4. Add the integration through the UI.
5. Validate changes with the service calls documented in [docs/SERVICES.md](docs/SERVICES.md).

## Testing Expectations

At minimum, validate the affected workflow manually in Home Assistant.

For backend changes, test:

- integration setup;
- `learn_and_read`;
- `test_code`;
- `save_command`;
- `send_command`;
- `list_commands`;
- Home Assistant restart with saved commands.

For storage changes, verify migration behavior and ensure existing saved commands remain usable.

For UI changes, verify both desktop and mobile layouts and ensure long base64 strings do not break the card layout.

## Release Rules for HACS

HACS detects this repository's released version from GitHub Releases, not from a
local tag alone. When publishing a release:

- update `custom_components/ir_learning_hub/manifest.json`;
- update `IR_LEARNING_HUB_CARD_VERSION` in the bundled Lovelace card when the
  frontend changed;
- update `CHANGELOG.md`, README release examples, and `docs/INSTALLATION.md`;
- commit the release metadata before tagging;
- create and push tag `vX.Y.Z` on that exact commit;
- verify the tag points at the release metadata commit, not an older commit;
- create a GitHub Release from `vX.Y.Z` and leave it non-draft; use prerelease
  only for builds HACS users should treat as prerelease;
- verify GitHub latest release reports the expected `tag_name` and
  `draft=false`.

Do not call a version released for HACS until both the tag and the GitHub
Release exist.

## Style Guidelines

- Keep changes focused and small enough to review.
- Prefer explicit error codes over parsing exception text.
- Treat IR payloads as opaque strings unless a profile-specific decoder is intentionally added.
- Do not add broad abstractions before there is a second real transport or device profile to justify them.

## Reporting Issues

When reporting a problem, include:

- Home Assistant version;
- ZHA status;
- device model and manufacturer string;
- active ZHA quirk;
- endpoint and cluster information;
- service call used;
- error code and log excerpt.

Do not include secrets, tokens, or unrelated Home Assistant logs.
