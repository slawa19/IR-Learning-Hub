"""Unit tests for pure registry storage migrations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from storage_migration import (  # noqa: E402
    migrate_to_v3,
    migrate_to_v4,
    migrate_to_v5,
    migrate_v1_to_v2,
    migrate_v2_to_v3,
    migrate_v3_to_v4,
    migrate_v4_to_v5,
)


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

        migrated = migrate_to_v3(v1_data)

        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["transmitters"], v1_data["transmitters"])
        device = migrated["locations"]["living_room"]["devices"]["receiver"]
        self.assertEqual(device["name"], "Receiver")
        self.assertEqual(device["type"], "media_player")
        self.assertEqual(device["commands"]["volume_up"]["feature"], "volume_up")
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

    def test_v2_to_v3_seeds_known_features_only(self) -> None:
        migrated = migrate_v2_to_v3(
            {
                "version": 2,
                "transmitters": {},
                "locations": {
                    "room": {
                        "devices": {
                            "amp": {
                                "name": "Amp",
                                "type": "media_player",
                                "preferred_domain": "media_player",
                                "transmitter_id": None,
                                "commands": {
                                    "power": {"name": "Power"},
                                    "vol_up": {"name": "Volume up"},
                                    "source_cd": {"name": "CD"},
                                    "tuner": {"name": "Tuner"},
                                    "video_1": {"name": "Video 1"},
                                },
                            }
                        }
                    }
                },
            }
        )

        commands = migrated["locations"]["room"]["devices"]["amp"]["commands"]
        self.assertEqual(commands["power"]["feature"], "power_toggle")
        self.assertEqual(commands["vol_up"]["feature"], "volume_up")
        self.assertEqual(commands["source_cd"]["feature"], "source")
        self.assertNotIn("feature", commands["tuner"])
        self.assertNotIn("feature", commands["video_1"])

    def test_v3_to_v4_canonicalizes_known_transmitter_refs(self) -> None:
        migrated = migrate_v3_to_v4(
            {
                "version": 3,
                "transmitters": {
                    "b0e8e8fffe16ef35": {"ieee": "b0:e8:e8:ff:fe:16:ef:35"}
                },
                "locations": {
                    "room": {
                        "devices": {
                            "amp": {
                                "name": "Amp",
                                "type": "media_player",
                                "transmitter_id": "ir_transmitter_b0_e8_e8_ff_fe_16_ef_35",
                                "commands": {},
                            }
                        }
                    }
                },
            }
        )

        device = migrated["locations"]["room"]["devices"]["amp"]
        self.assertEqual(device["transmitter_id"], "b0e8e8fffe16ef35")

    def test_v3_to_v4_clears_unknown_transmitter_refs(self) -> None:
        migrated = migrate_to_v4(
            {
                "version": 3,
                "transmitters": {"known": {"ieee": "00:11"}},
                "locations": {
                    "room": {
                        "devices": {
                            "amp": {
                                "name": "Amp",
                                "type": "media_player",
                                "transmitter_id": "infrared.ir_transmitter_dead_beef",
                                "commands": {},
                            },
                            "tv": {
                                "name": "TV",
                                "type": "generic",
                                "transmitter_id": "known",
                                "commands": {},
                            },
                        }
                    }
                },
            }
        )

        devices = migrated["locations"]["room"]["devices"]
        self.assertIsNone(devices["amp"]["transmitter_id"])
        self.assertEqual(devices["tv"]["transmitter_id"], "known")

    def test_v4_to_v5_reclassifies_generated_sony_sirc_mute_as_toggle(self) -> None:
        migrated = migrate_v4_to_v5(
            {
                "version": 4,
                "transmitters": {},
                "locations": {
                    "room": {
                        "devices": {
                            "amp": {
                                "commands": {
                                    "mute": {
                                        "feature": "mute",
                                        "source": {
                                            "type": "protocol",
                                            "protocol": "sony_sirc",
                                            "params": {"command": 20},
                                        },
                                    }
                                }
                            }
                        }
                    }
                },
            }
        )

        command = migrated["locations"]["room"]["devices"]["amp"]["commands"]["mute"]
        self.assertEqual(command["feature"], "mute_toggle")

    def test_v4_to_v5_keeps_non_matching_mute_records(self) -> None:
        data = {
            "version": 4,
            "transmitters": {},
            "locations": {
                "room": {
                    "devices": {
                        "amp": {
                            "commands": {
                                "learned": {"feature": "mute"},
                                "denon": {
                                    "feature": "mute",
                                    "source": {
                                        "type": "protocol",
                                        "protocol": "denon",
                                        "params": {"command": 20},
                                    },
                                },
                                "sony_other": {
                                    "feature": "mute",
                                    "source": {
                                        "type": "protocol",
                                        "protocol": "sony_sirc",
                                        "params": {"command": 21},
                                    },
                                },
                                "fixed": {
                                    "feature": "mute_toggle",
                                    "source": {
                                        "type": "protocol",
                                        "protocol": "sony_sirc",
                                        "params": {"command": 20},
                                    },
                                },
                            }
                        }
                    }
                }
            },
        }

        migrated = migrate_to_v5(data)
        commands = migrated["locations"]["room"]["devices"]["amp"]["commands"]

        self.assertEqual(commands["learned"]["feature"], "mute")
        self.assertEqual(commands["denon"]["feature"], "mute")
        self.assertEqual(commands["sony_other"]["feature"], "mute")
        self.assertEqual(commands["fixed"]["feature"], "mute_toggle")
        self.assertEqual(migrated["version"], 5)


if __name__ == "__main__":
    unittest.main()
