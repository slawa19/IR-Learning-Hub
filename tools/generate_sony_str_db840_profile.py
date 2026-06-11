"""Generate an IR Learning Hub import profile for Sony STR-DB840.

The output JSON matches the Lovelace card's device-profile import format:

    python tools/generate_sony_str_db840_profile.py
    python tools/generate_sony_str_db840_profile.py --output sony_str_db840.json

Import flow in the card:

    device menu -> Import profile -> paste JSON -> Import
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "ir_learning_hub"
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

from ir_formats import generate_protocol, zosung_encode  # noqa: E402
from ir_formats.protocols.sony_sirc import (  # noqa: E402
    CARRIER_HZ,
    DEFAULT_REPEATS,
    FRAME_PERIOD_US,
    MAX_REPEATS,
)


COMMANDS = [
    ("power_toggle", "Power", 21, "mdi:power"),
    ("volume_up", "Volume Up", 18, "mdi:volume-plus"),
    ("volume_down", "Volume Down", 19, "mdi:volume-minus"),
    ("mute", "Mute", 20, "mdi:volume-mute"),
    ("tuner", "Tuner / FM-AM", 33, "mdi:radio"),
    ("video_1", "Video 1", 34, "mdi:video-input-component"),
    ("video_2", "Video 2", 30, "mdi:video-input-component"),
    ("video_3", "Video 3", 66, "mdi:video-input-component"),
    ("cd", "CD", 37, "mdi:disc-player"),
    ("md_tape", "MD/Tape", 105, "mdi:cassette"),
    ("dvd_ld", "DVD/LD", 107, "mdi:disc"),
    ("dvd", "DVD", 125, "mdi:disc"),
    ("tv_sat", "TV/SAT", 106, "mdi:satellite-variant"),
]


def build_profile(
    *,
    device: int,
    bits: int,
    repeats: int,
    verified: bool,
    profile_name: str,
) -> dict[str, Any]:
    """Build a card-importable device profile."""
    commands: dict[str, Any] = {}

    for command_id, name, command, icon in COMMANDS:
        params = {
            "command": command,
            "device": device,
            "bits": bits,
            "extended": 0,
            "repeats": repeats,
            "frame_period_us": FRAME_PERIOD_US,
        }
        signal = generate_protocol("sony_sirc", params)
        commands[command_id] = {
            "name": name,
            "icon": icon,
            "code": zosung_encode(signal),
            "format": "zosung_base64",
            "verified": verified,
            "source": {
                "type": "protocol",
                "protocol": "sony_sirc",
                "carrier_frequency": signal.carrier_frequency,
                "params": params,
            },
        }

    return {
        "_profile": "ir_learning_hub",
        "version": 1,
        "name": profile_name,
        "type": "receiver",
        "commands": commands,
    }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Generate a Sony STR-DB840 profile for IR Learning Hub."
    )
    parser.add_argument(
        "--device",
        type=int,
        default=16,
        help="Sony SIRC device/address. Use 16 for the primary receiver mode.",
    )
    parser.add_argument(
        "--bits",
        type=int,
        choices=(12, 15, 20),
        default=12,
        help="Sony SIRC frame length. Use 15 for device 48 / AV2 candidates.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        choices=range(1, MAX_REPEATS + 1),
        metavar=f"1..{MAX_REPEATS}",
        help="Frame repeats to expand into the raw timings.",
    )
    parser.add_argument(
        "--verified",
        action="store_true",
        help="Mark generated commands as verified. Default is false.",
    )
    parser.add_argument(
        "--name",
        default="Sony STR-DB840",
        help="Profile display name.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON to this file instead of stdout.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    profile = build_profile(
        device=args.device,
        bits=args.bits,
        repeats=args.repeats,
        verified=args.verified,
        profile_name=args.name,
    )
    text = json.dumps(profile, indent=2, ensure_ascii=True) + "\n"

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output} ({len(profile['commands'])} commands)")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
