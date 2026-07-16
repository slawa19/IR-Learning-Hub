"""Unit tests for opaque infrared command wrappers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

if importlib.util.find_spec("infrared_protocols") is None:
    raise unittest.SkipTest("infrared_protocols is not installed")

from ir_command import (  # noqa: E402
    DEFAULT_MODULATION,
    ZOSUNG_FORMAT,
    ZosungCommand,
    command_code,
    command_send_payload,
)


class ZosungCommandTests(unittest.TestCase):
    def test_stores_opaque_payload_and_command_metadata(self) -> None:
        command = ZosungCommand(
            "encoded-code",
            repeat_count=2,
            location_id="living",
            ir_device_id="amp",
            command_id="power",
        )

        self.assertEqual(command.code, "encoded-code")
        self.assertEqual(command.format, ZOSUNG_FORMAT)
        self.assertEqual(command.modulation, DEFAULT_MODULATION)
        self.assertEqual(command.repeat_count, 2)
        self.assertEqual(command.location_id, "living")
        self.assertEqual(command.ir_device_id, "amp")
        self.assertEqual(command.command_id, "power")
        self.assertEqual(command_code(command), "encoded-code")

    def test_allows_explicit_format_and_modulation(self) -> None:
        command = ZosungCommand(
            "encoded-code",
            command_format="custom",
            modulation=40000,
        )

        self.assertEqual(command.format, "custom")
        self.assertEqual(command.modulation, 40000)

    def test_raw_timings_are_not_available_for_opaque_payload(self) -> None:
        with self.assertRaises(NotImplementedError):
            ZosungCommand("encoded-code").get_raw_timings()

    def test_command_code_requires_non_empty_code(self) -> None:
        with self.assertRaises(ValueError):
            command_code(ZosungCommand(""))

    def test_command_send_payload_returns_transmitter_and_code(self) -> None:
        transmitter = {"ieee": "00:11", "config": {}}

        payload_transmitter, code = command_send_payload(
            transmitter,
            ZosungCommand("encoded-code"),
        )

        self.assertIs(payload_transmitter, transmitter)
        self.assertEqual(code, "encoded-code")


if __name__ == "__main__":
    unittest.main()
