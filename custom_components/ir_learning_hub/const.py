"""Constants for IR Learning Hub."""

from __future__ import annotations

DOMAIN = "ir_learning_hub"
HUB_ENTRY_DATA = {"hub": True}
HUB_TITLE = "IR Learning Hub"
TRANSMITTER_SUBENTRY_TYPE = "transmitter"

SIGNAL_REGISTRY_UPDATED = f"{DOMAIN}_registry_updated"

CONF_CLUSTER_ID = "cluster_id"
CONF_ENDPOINT_ID = "endpoint_id"
CONF_IEEE = "ieee"
CONF_LEARN_REASSERT_INTERVAL = "learn_reassert_interval"
CONF_LEARN_TIMEOUT = "learn_timeout"
CONF_PROFILE = "profile"
CONF_ZHA_DEVICE = "zha_device"

DEFAULT_CLUSTER_ID = 0xE004
DEFAULT_ENDPOINT_ID = 1
DEFAULT_LEARN_REASSERT_INTERVAL = 8
DEFAULT_LEARN_TIMEOUT = 60
DEFAULT_PROFILE = "ts1201_zosung"

ERROR_CODE_EMPTY = "code_empty"
ERROR_CODE_GENERATION = "code_generation_failed"
ERROR_CLUSTER_NOT_FOUND = "cluster_not_found"
ERROR_COMMAND_NOT_FOUND = "command_not_found"
ERROR_LEARN_FAILED = "learn_failed"
ERROR_LEARN_TIMEOUT = "learn_timeout"
ERROR_SEND_FAILED = "send_failed"
ERROR_STORAGE_ERROR = "storage_error"
ERROR_TRANSMITTER_NOT_CONFIGURED = "transmitter_not_configured"
ERROR_TRANSMITTER_REQUIRED = "transmitter_required"
ERROR_TRANSMITTER_UNAVAILABLE = "transmitter_unavailable"
ERROR_UNKNOWN_PROFILE = "unknown_profile"
ERROR_UNEXPECTED = "unexpected_error"
ERROR_ZHA_DEVICE_NOT_FOUND = "zha_device_not_found"
ERROR_ZHA_UNAVAILABLE = "zha_unavailable"

SERVICE_ADD_COMMAND = "add_command"
SERVICE_ADD_DEVICE = "add_device"
SERVICE_ADD_LOCATION = "add_location"
SERVICE_DELETE_COMMAND = "delete_command"
SERVICE_DELETE_DEVICE = "delete_device"
SERVICE_DELETE_LOCATION = "delete_location"
SERVICE_GENERATE_CODE = "generate_code"
SERVICE_LEARN = "learn"
SERVICE_LEARN_AND_READ = "learn_and_read"
SERVICE_LIST_COMMANDS = "list_commands"
SERVICE_READ_LAST_CODE = "read_last_code"
SERVICE_RENAME_COMMAND = "rename_command"
SERVICE_RENAME_DEVICE = "rename_device"
SERVICE_RENAME_LOCATION = "rename_location"
SERVICE_SAVE_COMMAND = "save_command"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_TEST_CODE = "test_code"
SERVICE_UPDATE_COMMAND = "update_command"
SERVICE_UPDATE_DEVICE = "update_device"

FIELD_IR_DEVICE_ID = "ir_device_id"
FIELD_LOCATION_ID = "location_id"
FIELD_NAME = "name"
FIELD_PREFERRED_DOMAIN = "preferred_domain"
FIELD_TRANSMITTER_ID = "transmitter_id"
FIELD_TYPE = "type"

PREFERRED_DOMAIN_AUTO = "auto"
PREFERRED_DOMAINS = ("auto", "media_player", "remote", "switch")

COMMAND_FEATURES = (
    "power_on",
    "power_off",
    "power_toggle",
    "play",
    "pause",
    "play_pause_toggle",
    "stop",
    "next",
    "previous",
    "fast_forward",
    "rewind",
    "volume_up",
    "volume_down",
    "mute",
    "unmute",
    "mute_toggle",
    "source",
)

STATUS_CODE_RECEIVED = "code_received"
STATUS_ERROR = "error"
STATUS_IDLE = "idle"
STATUS_LEARNING = "learning"
STATUS_SENDING = "sending"
