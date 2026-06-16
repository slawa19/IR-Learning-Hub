"""Unit tests for pure command capability inference."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from capabilities import infer_capabilities, normalize_command_id, normalize_command_ids, source_display_name  # noqa: E402


class CommandNormalizationTests(unittest.TestCase):
    def test_aliases_normalize_to_canonical_ids(self) -> None:
        cases = {
            "vol_up": "volume_up",
            "vol_down": "volume_down",
            "power": "power_toggle",
            "forward": "fast_forward",
            "backward": "rewind",
            "ok": "select",
            "return": "back",
            "input_tv": "source_tv",
            "input_pc": "source_pc",
            "play": "play",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_command_id(raw), expected)

    def test_collection_normalization_deduplicates_aliases(self) -> None:
        self.assertEqual(
            normalize_command_ids(["vol_up", "volume_up", "input_pc"]),
            frozenset({"volume_up", "source_pc"}),
        )


class CapabilityInferenceTests(unittest.TestCase):
    def test_power_modes(self) -> None:
        cases = [
            ({"power_on", "power_off"}, "explicit", False),
            ({"power"}, "toggle", True),
            ({"play"}, "none", False),
        ]
        for commands, power_mode, assumed in cases:
            with self.subTest(commands=commands):
                capabilities = infer_capabilities(commands)
                self.assertEqual(capabilities.power_mode, power_mode)
                self.assertEqual(capabilities.assumed_power, assumed)

    def test_media_features_from_command_ids(self) -> None:
        capabilities = infer_capabilities(
            {
                "play",
                "play_pause_toggle",
                "stop",
                "next",
                "previous",
                "vol_up",
                "vol_down",
                "mute_toggle",
                "source_video_1",
            }
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

    def test_sources_are_sorted_and_formatted(self) -> None:
        capabilities = infer_capabilities({"source_pc", "source_video_1", "source_home_ass"})
        self.assertEqual(
            capabilities.source_commands,
            ("source_home_ass", "source_pc", "source_video_1"),
        )
        self.assertEqual(
            capabilities.source_names,
            {
                "source_home_ass": "Home Ass",
                "source_pc": "PC",
                "source_video_1": "Video 1",
            },
        )
        self.assertEqual(source_display_name("source_hdmi_2"), "HDMI 2")

    def test_pure_switch_detection(self) -> None:
        self.assertTrue(infer_capabilities({"power_on", "power_off"}).is_pure_switch)
        self.assertTrue(infer_capabilities({"power_toggle"}).is_pure_switch)
        self.assertFalse(infer_capabilities({"power_toggle", "play"}).is_pure_switch)


if __name__ == "__main__":
    unittest.main()
