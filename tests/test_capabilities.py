"""Unit tests for pure command capability inference."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from capabilities import infer_capabilities, normalize_command_id, normalize_command_ids, seed_feature_from_command_id  # noqa: E402


class CommandNormalizationTests(unittest.TestCase):
    def test_aliases_normalize_to_canonical_seed_ids(self) -> None:
        cases = {
            "vol_up": "volume_up",
            "vol_down": "volume_down",
            "power": "power_toggle",
            "forward": "fast_forward",
            "backward": "rewind",
            "input_tv": "source",
            "play": "play",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_command_id(raw), expected)

    def test_collection_normalization_deduplicates_aliases(self) -> None:
        self.assertEqual(
            normalize_command_ids(["vol_up", "volume_up", "input_pc"]),
            frozenset({"volume_up", "source"}),
        )

    def test_seed_feature_from_legacy_command_id(self) -> None:
        cases = {
            "power": "power_toggle",
            "volume_up": "volume_up",
            "vol_down": "volume_down",
            "source_cd": "source",
            "input_pc": "source",
            "tuner": None,
            "cd": None,
            "video_1": None,
        }
        for command_id, expected in cases.items():
            with self.subTest(command_id=command_id):
                self.assertEqual(seed_feature_from_command_id(command_id), expected)


class CapabilityInferenceTests(unittest.TestCase):
    def test_power_modes_from_explicit_features(self) -> None:
        cases = [
            ({"power_on", "power_off"}, "explicit", False),
            ({"power_toggle"}, "toggle", True),
            ({"play"}, "none", False),
        ]
        for features, power_mode, assumed in cases:
            with self.subTest(features=features):
                capabilities = infer_capabilities(
                    [
                        {"command_id": feature, "feature": feature, "name": feature}
                        for feature in features
                    ]
                )
                self.assertEqual(capabilities.power_mode, power_mode)
                self.assertEqual(capabilities.assumed_power, assumed)

    def test_media_features_from_explicit_features(self) -> None:
        capabilities = infer_capabilities(
            [
                {"command_id": "a", "feature": "play", "name": "Play"},
                {"command_id": "b", "feature": "play_pause_toggle", "name": "Pause"},
                {"command_id": "c", "feature": "stop", "name": "Stop"},
                {"command_id": "d", "feature": "next", "name": "Next"},
                {"command_id": "e", "feature": "previous", "name": "Previous"},
                {"command_id": "f", "feature": "volume_up", "name": "Vol +"},
                {"command_id": "g", "feature": "volume_down", "name": "Vol -"},
                {"command_id": "h", "feature": "mute_toggle", "name": "Mute"},
                {"command_id": "i", "feature": "source", "name": "CD"},
            ]
        )
        self.assertEqual(
            capabilities.media_features,
            frozenset(
                {
                    "play",
                    "pause",
                    "stop",
                    "next",
                    "previous",
                    "volume_step",
                    "mute",
                    "source",
                }
            ),
        )

    def test_sources_use_command_names_as_labels(self) -> None:
        capabilities = infer_capabilities(
            [
                {"command_id": "tuner", "feature": "source", "name": "Tuner"},
                {"command_id": "cd", "feature": "source", "name": "CD"},
            ]
        )
        self.assertEqual(capabilities.source_commands, ("cd", "tuner"))
        self.assertEqual(capabilities.source_names, {"cd": "CD", "tuner": "Tuner"})

    def test_pure_switch_detection(self) -> None:
        self.assertTrue(
            infer_capabilities(
                [
                    {"command_id": "on", "feature": "power_on", "name": "On"},
                    {"command_id": "off", "feature": "power_off", "name": "Off"},
                ]
            ).is_pure_switch
        )
        self.assertTrue(
            infer_capabilities(
                [{"command_id": "toggle", "feature": "power_toggle", "name": "Power"}]
            ).is_pure_switch
        )
        self.assertFalse(
            infer_capabilities(
                [
                    {"command_id": "toggle", "feature": "power_toggle", "name": "Power"},
                    {"command_id": "play", "feature": "play", "name": "Play"},
                ]
            ).is_pure_switch
        )


if __name__ == "__main__":
    unittest.main()
