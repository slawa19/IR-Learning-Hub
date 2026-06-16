"""Unit tests for pure registry storage migrations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from storage_migration import migrate_v1_to_v2  # noqa: E402


class StorageMigrationTests(unittest.TestCase):
    def test_v1_to_v2_preserves_existing_registry_data(self) -> None:
        v1_data = {
            "version": 1,
            "transmitters": {
                "tx1": {
                    "ieee": "00:11",
                    "name": "Transmitter",
                    "enabled": True,
                }
            },
            "locations": {
                "living_room": {
                    "name": "Living room",
                    "devices": {
                        "receiver": {
                            "name": "Receiver",
                            "type": "media_player",
                            "commands": {
                                "volume_up": {
                                    "name": "Volume up",
                                    "code": "abc",
                                    "format": "zosung_base64",
                                    "verified": True,
                                }
                            },
                        }
                    },
                }
            },
        }

        migrated = migrate_v1_to_v2(v1_data)

        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["transmitters"], v1_data["transmitters"])
        device = migrated["locations"]["living_room"]["devices"]["receiver"]
        self.assertEqual(device["name"], "Receiver")
        self.assertEqual(device["type"], "media_player")
        self.assertEqual(device["commands"], v1_data["locations"]["living_room"]["devices"]["receiver"]["commands"])
        self.assertEqual(device["preferred_domain"], "auto")
        self.assertIsNone(device["transmitter_id"])

    def test_v1_to_v2_does_not_mutate_input(self) -> None:
        v1_data = {
            "version": 1,
            "transmitters": {},
            "locations": {
                "room": {
                    "name": "Room",
                    "devices": {
                        "tv": {
                            "name": "TV",
                            "type": "generic",
                            "commands": {},
                        }
                    },
                }
            },
        }

        migrate_v1_to_v2(v1_data)

        device = v1_data["locations"]["room"]["devices"]["tv"]
        self.assertNotIn("preferred_domain", device)
        self.assertNotIn("transmitter_id", device)

    def test_v1_to_v2_keeps_existing_v2_like_fields(self) -> None:
        migrated = migrate_v1_to_v2(
            {
                "version": 1,
                "transmitters": {},
                "locations": {
                    "room": {
                        "name": "Room",
                        "devices": {
                            "amp": {
                                "name": "Amp",
                                "type": "media_player",
                                "preferred_domain": "media_player",
                                "transmitter_id": "tx1",
                                "commands": {},
                            }
                        },
                    }
                },
            }
        )

        device = migrated["locations"]["room"]["devices"]["amp"]
        self.assertEqual(device["preferred_domain"], "media_player")
        self.assertEqual(device["transmitter_id"], "tx1")


if __name__ == "__main__":
    unittest.main()
