"""Unit tests for pure registry runtime projection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from registry_runtime import desired_entities, diff_entity_ids  # noqa: E402


class RegistryRuntimeTests(unittest.TestCase):
    def test_desired_entities_select_domains_from_preference_and_type(self) -> None:
        store_data = {
            "locations": {
                "living": {
                    "name": "Living",
                    "devices": {
                        "amp": {
                            "name": "Amp",
                            "type": "media_player",
                            "preferred_domain": "auto",
                            "transmitter_id": "tx1",
                            "commands": {"play": {}, "vol_up": {}, "vol_down": {}},
                        },
                        "tv": {
                            "name": "TV",
                            "type": "generic",
                            "preferred_domain": "remote",
                            "commands": {"power": {}},
                        },
                        "lamp": {
                            "name": "Lamp",
                            "type": "switch",
                            "preferred_domain": "auto",
                            "commands": {"power_on": {}, "power_off": {}},
                        },
                    },
                }
            }
        }

        specs = {spec.unique_id: spec for spec in desired_entities(store_data)}

        self.assertEqual(specs["living__amp"].domain, "media_player")
        self.assertEqual(specs["living__amp"].command_keys["volume_up"], "vol_up")
        self.assertEqual(specs["living__amp"].transmitter_id, "tx1")
        self.assertEqual(specs["living__tv"].domain, "remote")
        self.assertEqual(specs["living__tv"].command_keys["power_toggle"], "power")
        self.assertEqual(specs["living__lamp__switch"].domain, "switch")

    def test_preferred_switch_falls_back_to_remote_when_not_pure_switch(self) -> None:
        store_data = {
            "locations": {
                "room": {
                    "devices": {
                        "mixed": {
                            "name": "Mixed",
                            "type": "generic",
                            "preferred_domain": "switch",
                            "commands": {"power_toggle": {}, "play": {}},
                        }
                    }
                }
            }
        }

        [spec] = desired_entities(store_data)

        self.assertEqual(spec.domain, "remote")
        self.assertEqual(spec.unique_id, "room__mixed")

    def test_diff_entity_ids_is_idempotent(self) -> None:
        desired = {
            "a": object(),
            "b": object(),
        }

        add_ids, remove_ids = diff_entity_ids({"b", "c"}, desired)

        self.assertEqual(add_ids, {"a"})
        self.assertEqual(remove_ids, {"c"})


if __name__ == "__main__":
    unittest.main()
