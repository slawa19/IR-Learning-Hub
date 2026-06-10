"""Known IR transmitter profiles."""

from __future__ import annotations

from .const import ERROR_UNKNOWN_PROFILE
from .errors import IRLearningHubError

PROFILES: dict[str, dict] = {
    "ts1201_zosung": {
        "description": "Tuya TS1201 / MOES UFO-R11 with ZosungIRBlaster quirk",
        "endpoint_id": 1,
        "ir_control_cluster": 0xE004,
        "ir_transmit_cluster": 0xED00,
        "learn_command": {
            "command": 1,
            "params_true": {"on_off": True},
            "params_false": {"on_off": False},
        },
        "send_command": {
            "command": 2,
            "params_template": {"code": "{ir_code}"},
        },
        "last_learned_attribute": "last_learned_ir_code",
        "last_learned_attribute_id": 0x0000,
        "learn_reassert_interval": 8,
        "learning_timeout": 60,
        "format": "zosung_base64",
    }
}


def get_profile(profile_id: str) -> dict:
    """Return a known transmitter profile."""
    try:
        return PROFILES[profile_id]
    except KeyError as err:
        raise IRLearningHubError(
            ERROR_UNKNOWN_PROFILE,
            f"Unknown IR transmitter profile: {profile_id}",
        ) from err
