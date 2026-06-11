"""Unit tests for the pure ir_formats package.

These tests deliberately import ir_formats as a standalone top-level package so
they do not pull in the Home Assistant-dependent integration __init__. Run with:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ir_learning_hub"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

import ir_formats  # noqa: E402
from ir_formats import IRFormatError, IRSignal  # noqa: E402
from ir_formats.protocols.sony_sirc import (  # noqa: E402
    FRAME_PERIOD_US,
    HEADER_MARK_US,
    UNIT_US,
    encode_sony_sirc,
)
from ir_formats.zosung import _compress, _decompress  # noqa: E402


class ZosungCodecTests(unittest.TestCase):
    def test_roundtrip_signal_level(self) -> None:
        signal = IRSignal(timings=[9000, 4500, 560, 560, 560, 1690], carrier_frequency=38000)
        decoded = ir_formats.zosung_decode(ir_formats.zosung_encode(signal))
        self.assertEqual(decoded.timings, signal.timings)

    def test_fastlz_decompresses_back_references(self) -> None:
        # Hand-built stream: literal "AB" then a back-reference copying 4 bytes
        # from distance 2 (overlapping). 2 literals + 4 copied = "ABABAB".
        literal = bytes([0x01, ord("A"), ord("B")])  # run of 2 literals
        # length field: stored value 2 in top 3 bits -> actual copy len = 2 + 2;
        # distance-1 = 1 -> distance 2.
        match = bytes([(2 << 5) | 0x00, 0x01])
        self.assertEqual(_decompress(literal + match), b"ABABAB")

    def test_compress_is_literal_only_and_reversible(self) -> None:
        payload = bytes(range(100))
        self.assertEqual(_decompress(_compress(payload)), payload)

    def test_decode_rejects_bad_base64(self) -> None:
        with self.assertRaises(IRFormatError):
            ir_formats.zosung_decode("not base64 !!!")


class IRSignalModelTests(unittest.TestCase):
    def test_rejects_empty(self) -> None:
        with self.assertRaises(IRFormatError):
            IRSignal(timings=[])

    def test_rejects_non_positive(self) -> None:
        with self.assertRaises(IRFormatError):
            IRSignal(timings=[600, 0, 600])

    def test_rejects_overflow(self) -> None:
        with self.assertRaises(IRFormatError):
            IRSignal(timings=[70000])


class SonySircTests(unittest.TestCase):
    def test_volume_up_bit_order_lsb_first(self) -> None:
        # SIRC-12 Volume Up: command 18, device 16.
        signal = encode_sony_sirc(command=18, device=16, bits=12, repeats=1)
        # One frame: header (2 entries) + 12 bits * 2 entries = 26 entries.
        self.assertEqual(len(signal.timings), 26)
        self.assertEqual(signal.timings[0], HEADER_MARK_US)
        self.assertEqual(signal.timings[1], UNIT_US)
        self.assertEqual(signal.carrier_frequency, 40000)

        # command 18 = 0b0010010 -> LSB first: 0,1,0,0,1,0,0
        # device 16  = 0b10000   -> LSB first: 0,0,0,0,1
        expected_bits = [0, 1, 0, 0, 1, 0, 0] + [0, 0, 0, 0, 1]
        marks = signal.timings[2::2]  # mark of each bit
        decoded_bits = [1 if mark == 2 * UNIT_US else 0 for mark in marks]
        self.assertEqual(decoded_bits, expected_bits)

    def test_repeats_and_frame_period(self) -> None:
        one = encode_sony_sirc(command=18, device=16, bits=12, repeats=1)
        three = encode_sony_sirc(command=18, device=16, bits=12, repeats=3)
        self.assertEqual(len(three.timings), 3 * len(one.timings))
        # Each frame should sum to the 45 ms frame period.
        frame_len = len(one.timings)
        self.assertEqual(sum(one.timings), FRAME_PERIOD_US)
        self.assertEqual(sum(three.timings[:frame_len]), FRAME_PERIOD_US)

    def test_generated_signal_survives_zosung_roundtrip(self) -> None:
        signal = encode_sony_sirc(command=21, device=16, bits=12)  # Power
        decoded = ir_formats.zosung_decode(ir_formats.zosung_encode(signal))
        self.assertEqual(decoded.timings, signal.timings)

    def test_rejects_out_of_range_command(self) -> None:
        with self.assertRaises(IRFormatError):
            encode_sony_sirc(command=200, device=16, bits=12)

    def test_rejects_excessive_repeats(self) -> None:
        with self.assertRaises(IRFormatError):
            encode_sony_sirc(command=18, device=16, bits=12, repeats=100000)

    def test_dispatch_via_registry(self) -> None:
        self.assertIn("sony_sirc", ir_formats.list_protocols())
        signal = ir_formats.generate_protocol(
            "sony_sirc", {"command": 18, "device": 16, "bits": 12}
        )
        self.assertEqual(signal.carrier_frequency, 40000)


if __name__ == "__main__":
    unittest.main()
