"""IR Learning Hub integration."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    COMMAND_FEATURES,
    CONF_CLUSTER_ID,
    CONF_ENDPOINT_ID,
    CONF_IEEE,
    CONF_LEARN_REASSERT_INTERVAL,
    CONF_LEARN_TIMEOUT,
    CONF_PROFILE,
    DOMAIN,
    ERROR_CODE_EMPTY,
    ERROR_CODE_GENERATION,
    ERROR_LEARN_TIMEOUT,
    ERROR_UNEXPECTED,
    SERVICE_ADD_COMMAND,
    SERVICE_ADD_DEVICE,
    SERVICE_ADD_LOCATION,
    SERVICE_DELETE_COMMAND,
    SERVICE_DELETE_DEVICE,
    SERVICE_DELETE_LOCATION,
    SERVICE_GENERATE_CODE,
    SERVICE_LEARN,
    SERVICE_LEARN_AND_READ,
    SERVICE_LIST_COMMANDS,
    SERVICE_READ_LAST_CODE,
    SERVICE_RENAME_COMMAND,
    SERVICE_RENAME_DEVICE,
    SERVICE_RENAME_LOCATION,
    SERVICE_SAVE_COMMAND,
    SERVICE_SEND_COMMAND,
    SERVICE_TEST_CODE,
    SERVICE_UPDATE_COMMAND,
    SERVICE_UPDATE_DEVICE,
    STATUS_CODE_RECEIVED,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_LEARNING,
    STATUS_SENDING,
    HUB_ENTRY_DATA,
    PREFERRED_DOMAINS,
    TRANSMITTER_SUBENTRY_TYPE,
)
from .errors import IRLearningHubError
from .ir_formats import (
    IRFormatError,
    generate_protocol,
    list_protocols,
    zosung_encode,
)
from .status import HubStatus
from .storage import IRRegistryStore, normalize_ieee
from .transmitter_identity import canonical_emitter_entity_id, normalize_transmitter_ref
from .zha_adapter import ZHAAdapter

PLATFORMS = [
    Platform.SENSOR,
    Platform.INFRARED,
    Platform.REMOTE,
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)
FRONTEND_URL = "/ir_learning_hub/ir-learning-hub-card.js"
FRONTEND_ICON_URL = "/ir_learning_hub/icon.png"

FIELD_BITS = "bits"
FIELD_CARRIER_FREQUENCY = "carrier_frequency"
FIELD_CODE = "code"
FIELD_COMMAND = "command"
FIELD_COMMAND_ID = "command_id"
FIELD_CONFIRM = "confirm"
FIELD_DEVICE = "device"
FIELD_EXTENDED = "extended"
FIELD_FEATURE = "feature"
FIELD_ICON = "icon"
FIELD_IR_DEVICE_ID = "ir_device_id"
FIELD_LOCATION_ID = "location_id"
FIELD_NAME = "name"
FIELD_POLL_INTERVAL = "poll_interval"
FIELD_PREFERRED_DOMAIN = "preferred_domain"
FIELD_PROTOCOL = "protocol"
FIELD_REPEATS = "repeats"
FIELD_SOURCE = "source"
FIELD_TIMEOUT = "timeout"
FIELD_TRANSMITTER_ID = "transmitter_id"
FIELD_TYPE = "type"
FIELD_VERIFIED = "verified"
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
SONY_SIRC_BITS = (12, 15, 20)
SONY_SIRC_FRAME_PERIOD_US = 45000
GENERATE_MAX_REPEATS = 20
REGISTERED_SERVICES = (
    SERVICE_LEARN,
    SERVICE_READ_LAST_CODE,
    SERVICE_LEARN_AND_READ,
    SERVICE_TEST_CODE,
    SERVICE_GENERATE_CODE,
    SERVICE_SAVE_COMMAND,
    SERVICE_SEND_COMMAND,
    SERVICE_LIST_COMMANDS,
    SERVICE_ADD_LOCATION,
    SERVICE_ADD_DEVICE,
    SERVICE_ADD_COMMAND,
    SERVICE_UPDATE_COMMAND,
    SERVICE_UPDATE_DEVICE,
    SERVICE_RENAME_LOCATION,
    SERVICE_RENAME_DEVICE,
    SERVICE_RENAME_COMMAND,
    SERVICE_DELETE_LOCATION,
    SERVICE_DELETE_DEVICE,
    SERVICE_DELETE_COMMAND,
)


def _id_schema(value: str) -> str:
    """Validate a stable registry ID."""
    value = cv.string(value).strip()
    if not ID_PATTERN.fullmatch(value):
        raise vol.Invalid("ID must match [a-z0-9_]+")
    return value


def _non_empty_string(value: str) -> str:
    """Validate a non-empty service string."""
    value = cv.string(value).strip()
    if not value:
        raise vol.Invalid("Value must not be empty")
    return value


def _optional_string(value: str) -> str:
    """Validate an optional service string that may be empty to clear it."""
    return cv.string(value).strip()


def _icon_schema(value: str) -> str:
    """Validate a Material Design icon name or an empty string to clear it."""
    value = cv.string(value).strip()
    if value and not value.startswith("mdi:"):
        raise vol.Invalid("Icon must start with mdi:")
    return value


def _command_update_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Require update_command to change at least one user-facing field."""
    if FIELD_NAME not in value and FIELD_ICON not in value and FIELD_FEATURE not in value:
        raise vol.Invalid("Either name, icon, or feature is required")
    return value


def _device_update_schema(value: dict[str, Any]) -> dict[str, Any]:
    """Require update_device to change at least one device metadata field."""
    update_fields = {
        FIELD_NAME,
        FIELD_TYPE,
        FIELD_PREFERRED_DOMAIN,
        FIELD_TRANSMITTER_ID,
    }
    if not update_fields & value.keys():
        raise vol.Invalid("At least one device field is required")
    return value


OPTIONAL_TRANSMITTER = {vol.Optional(FIELD_TRANSMITTER_ID): _non_empty_string}
LOCATION_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_NAME): _non_empty_string,
}
DEVICE_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
    vol.Required(FIELD_NAME): _non_empty_string,
    vol.Optional(FIELD_TYPE, default="generic"): _non_empty_string,
    vol.Optional(FIELD_PREFERRED_DOMAIN): vol.In(PREFERRED_DOMAINS),
    vol.Optional(FIELD_TRANSMITTER_ID): _optional_string,
}
COMMAND_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
    vol.Required(FIELD_COMMAND_ID): _id_schema,
    vol.Required(FIELD_NAME): _non_empty_string,
    vol.Optional(FIELD_FEATURE): vol.In(("",) + COMMAND_FEATURES),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Run one-time component setup and legacy entry migration."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("migration_ran"):
        return True

    domain_data["migration_ran"] = True
    await _async_migrate_legacy_entries_to_hub(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IR Learning Hub from the single hub config entry."""
    hass.data.setdefault(DOMAIN, {})
    domain_data = hass.data[DOMAIN]

    if "store" not in domain_data:
        store = IRRegistryStore(hass)
        await store.async_load()
        domain_data["store"] = store
        domain_data["status"] = HubStatus()
        domain_data["adapter"] = ZHAAdapter(hass)
        domain_data["learn_tasks"] = {}

    if not domain_data.get("frontend_registered"):
        await _async_register_frontend(hass)
        domain_data["frontend_registered"] = True

    store: IRRegistryStore = domain_data["store"]
    transmitter_subentries = _transmitter_subentries(entry)
    for subentry in transmitter_subentries:
        transmitter_id = await store.async_upsert_transmitter_from_entry(dict(subentry.data))
        _register_transmitter_device(hass, entry, subentry, transmitter_id)

    valid_transmitter_ids = {
        normalize_ieee(subentry.data[CONF_IEEE])
        for subentry in transmitter_subentries
    }
    await store.async_reconcile_transmitters(valid_transmitter_ids)

    if not domain_data.get("services_registered"):
        _register_services(hass)
        domain_data["services_registered"] = True

    entry.async_on_unload(entry.add_update_listener(_async_handle_entry_update))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN)
        if domain_data is not None:
            _teardown_domain(hass, domain_data)
    return unload_ok


def _teardown_domain(hass: HomeAssistant, domain_data: dict[str, Any]) -> None:
    """Remove global resources after the last config entry is deleted."""
    for task in domain_data.get("learn_tasks", {}).values():
        task.cancel()

    for service in REGISTERED_SERVICES:
        hass.services.async_remove(DOMAIN, service)

    hass.data.pop(DOMAIN, None)


async def _async_migrate_legacy_entries_to_hub(hass: HomeAssistant) -> None:
    """Reshape legacy one-transmitter-per-entry installs into hub + subentries."""
    entries = list(hass.config_entries.async_entries(DOMAIN))
    legacy_entries = [entry for entry in entries if _is_legacy_transmitter_entry(entry)]
    if not legacy_entries:
        return

    hub_entry = next((entry for entry in entries if _transmitter_subentries(entry)), None)
    if hub_entry is None:
        hub_entry = min(legacy_entries, key=_entry_sort_key)
        hub_transmitter = _legacy_transmitter_data(hub_entry)
        if hub_transmitter is not None:
            _ensure_transmitter_subentry(hass, hub_entry, hub_transmitter, hub_entry.title)
        hass.config_entries.async_update_entry(hub_entry, data=HUB_ENTRY_DATA)

    for legacy_entry in legacy_entries:
        if legacy_entry.entry_id == hub_entry.entry_id:
            continue
        transmitter_data = _legacy_transmitter_data(legacy_entry)
        if transmitter_data is None:
            continue
        _ensure_transmitter_subentry(
            hass,
            hub_entry,
            transmitter_data,
            legacy_entry.title,
        )
        await hass.config_entries.async_remove(legacy_entry.entry_id)


def _entry_sort_key(entry: ConfigEntry) -> tuple[str, str]:
    """Return a stable oldest-entry ordering key."""
    created_at = getattr(entry, "created_at", None)
    return (created_at.isoformat() if created_at is not None else "", entry.entry_id)


def _transmitter_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return transmitter subentries for the hub entry."""
    return entry.get_subentries_of_type(TRANSMITTER_SUBENTRY_TYPE)


def _is_legacy_transmitter_entry(entry: ConfigEntry) -> bool:
    """Return whether an entry is still in the pre-hub transmitter shape."""
    return CONF_IEEE in entry.data and not _transmitter_subentries(entry)


def _legacy_transmitter_data(entry: ConfigEntry) -> dict[str, Any] | None:
    """Extract transmitter subentry data from a legacy entry."""
    if CONF_IEEE not in entry.data:
        return None
    return {
        CONF_IEEE: entry.data[CONF_IEEE],
        CONF_PROFILE: entry.data[CONF_PROFILE],
        CONF_ENDPOINT_ID: entry.data[CONF_ENDPOINT_ID],
        CONF_CLUSTER_ID: entry.data[CONF_CLUSTER_ID],
        CONF_LEARN_TIMEOUT: entry.data[CONF_LEARN_TIMEOUT],
        CONF_LEARN_REASSERT_INTERVAL: entry.data[CONF_LEARN_REASSERT_INTERVAL],
    }


def _ensure_transmitter_subentry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    transmitter_data: dict[str, Any],
    title: str,
) -> None:
    """Add a transmitter subentry if one with the same canonical key is missing."""
    unique_id = normalize_ieee(str(transmitter_data[CONF_IEEE]).strip().lower())
    if any(subentry.unique_id == unique_id for subentry in _transmitter_subentries(entry)):
        return

    normalized_data = dict(transmitter_data)
    normalized_data[CONF_IEEE] = str(transmitter_data[CONF_IEEE]).strip().lower()
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType(normalized_data),
            subentry_type=TRANSMITTER_SUBENTRY_TYPE,
            title=title,
            unique_id=unique_id,
        ),
    )


def _register_transmitter_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    transmitter_id: str,
) -> None:
    """Register the integration transmitter device before entities attach to it."""
    ieee = str(subentry.data[CONF_IEEE]).strip().lower()
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=subentry.subentry_id,
        identifiers={(DOMAIN, transmitter_id)},
        via_device=("zha", ieee),
        name=f"IR transmitter {ieee}",
        manufacturer="Tuya",
        model="TS1201 / MOES UFO-R11",
    )


async def _async_handle_entry_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Reload the hub entry when subentries change."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card from the integration directory."""
    try:
        from homeassistant.components.http import StaticPathConfig

        integration_path = Path(__file__).parent
        card_path = integration_path / "www" / "ir-learning-hub-card.js"
        icon_path = integration_path / "icon.png"
        if not icon_path.exists():
            icon_path = integration_path / "brand" / "icon.png"
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(FRONTEND_URL, str(card_path), False),
                StaticPathConfig(FRONTEND_ICON_URL, str(icon_path), True),
            ]
        )
    except Exception as err:
        _LOGGER.warning("Could not register IR Learning Hub frontend: %s", err)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    store: IRRegistryStore = hass.data[DOMAIN]["store"]
    adapter: ZHAAdapter = hass.data[DOMAIN]["adapter"]
    status: HubStatus = hass.data[DOMAIN]["status"]
    learn_tasks: dict[str, asyncio.Task] = hass.data[DOMAIN]["learn_tasks"]

    def transmitter(data: dict[str, Any]) -> dict[str, Any]:
        transmitter_ref = data.get(FIELD_TRANSMITTER_ID)
        if transmitter_ref:
            canonical = resolve_transmitter_ref(hass, store, transmitter_ref)
            return store.resolve_transmitter(canonical)
        return store.resolve_transmitter(None)

    async def run_service(
        action: str,
        func: Callable[[], Any],
        *,
        status_state: str = STATUS_IDLE,
        start_status_state: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        if start_status_state:
            status.async_set(
                start_status_state,
                action=action,
                location_id=(data or {}).get(FIELD_LOCATION_ID),
                ir_device_id=(data or {}).get(FIELD_IR_DEVICE_ID),
                command_id=(data or {}).get(FIELD_COMMAND_ID),
            )

        try:
            result = await func()
            status.async_set(
                status_state,
                action=action,
                location_id=(data or {}).get(FIELD_LOCATION_ID),
                ir_device_id=(data or {}).get(FIELD_IR_DEVICE_ID),
                command_id=(data or {}).get(FIELD_COMMAND_ID),
            )
            return result
        except IRLearningHubError as err:
            status.async_set(
                STATUS_ERROR,
                action=action,
                location_id=(data or {}).get(FIELD_LOCATION_ID),
                ir_device_id=(data or {}).get(FIELD_IR_DEVICE_ID),
                command_id=(data or {}).get(FIELD_COMMAND_ID),
                error=err.code,
                error_message=err.message,
            )
            raise
        except Exception as err:
            status.async_set(
                STATUS_ERROR,
                action=action,
                location_id=(data or {}).get(FIELD_LOCATION_ID),
                ir_device_id=(data or {}).get(FIELD_IR_DEVICE_ID),
                command_id=(data or {}).get(FIELD_COMMAND_ID),
                error=ERROR_UNEXPECTED,
                error_message=str(err),
            )
            raise

    async def keep_learning_window(
        tx: dict[str, Any],
        timeout: int,
        first_reassert_after: int,
        task_key: str,
    ) -> None:
        """Keep a sleepy TS1201 in learn mode for the requested window."""
        elapsed = 0
        try:
            while elapsed + first_reassert_after < timeout:
                await asyncio.sleep(first_reassert_after)
                elapsed += first_reassert_after
                await adapter.async_learn(tx)
            remaining = timeout - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            if learn_tasks.get(task_key) is asyncio.current_task():
                status.async_set(STATUS_IDLE, action=SERVICE_LEARN)
        except asyncio.CancelledError:
            raise
        except IRLearningHubError as err:
            if learn_tasks.get(task_key) is asyncio.current_task():
                status.async_set(
                    STATUS_ERROR,
                    action=SERVICE_LEARN,
                    error=err.code,
                    error_message=err.message,
                )
        except Exception as err:
            if learn_tasks.get(task_key) is asyncio.current_task():
                status.async_set(
                    STATUS_ERROR,
                    action=SERVICE_LEARN,
                    error=ERROR_UNEXPECTED,
                    error_message=str(err),
                )

    def cancel_learn_window(tx: dict[str, Any]) -> None:
        """Cancel background learn reassertion for one transmitter."""
        task = learn_tasks.pop(tx["ieee"], None)
        if task:
            task.cancel()

    def schedule_learn_window(tx: dict[str, Any], timeout: int) -> None:
        """Schedule background learn reassertion for one transmitter."""
        task_key = tx["ieee"]
        cancel_learn_window(tx)

        interval = tx["config"].get("learn_reassert_interval", 8)
        task = hass.async_create_task(
            keep_learning_window(tx, timeout, interval, task_key)
        )
        learn_tasks[task_key] = task

        def cleanup(done_task: asyncio.Task) -> None:
            if learn_tasks.get(task_key) is done_task:
                learn_tasks.pop(task_key, None)

        task.add_done_callback(cleanup)

    async def learn(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            tx = transmitter(call.data)
            await adapter.async_learn(tx)
            schedule_learn_window(tx, call.data[FIELD_TIMEOUT])
            return {"status": "learn_started"}

        return await run_service(
            SERVICE_LEARN, action, status_state=STATUS_LEARNING, data=call.data
        )

    async def read_last_code(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            code = await adapter.async_read_last_code(transmitter(call.data))
            if not code:
                raise IRLearningHubError(
                    ERROR_CODE_EMPTY,
                    "Last learned IR code is empty",
                )
            return {"code": code}

        return await run_service(
            SERVICE_READ_LAST_CODE,
            action,
            status_state=STATUS_CODE_RECEIVED,
            data=call.data,
        )

    async def learn_and_read(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            tx = transmitter(call.data)
            cancel_learn_window(tx)
            timeout = call.data[FIELD_TIMEOUT]
            poll_interval = call.data[FIELD_POLL_INTERVAL]
            reassert_interval = tx["config"].get("learn_reassert_interval", 8)
            previous = await adapter.async_read_last_code(tx)

            await adapter.async_learn(tx)
            elapsed = 0.0
            next_reassert = float(reassert_interval)
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                code = await adapter.async_read_last_code(tx)
                if code and code != previous:
                    return {"code": code}

                if elapsed >= next_reassert:
                    await adapter.async_learn(tx)
                    next_reassert += reassert_interval

            raise IRLearningHubError(
                ERROR_LEARN_TIMEOUT,
                f"No new IR code was learned within {timeout} seconds",
            )

        return await run_service(
            SERVICE_LEARN_AND_READ,
            action,
            status_state=STATUS_CODE_RECEIVED,
            start_status_state=STATUS_LEARNING,
            data=call.data,
        )

    async def test_code(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await adapter.async_send(transmitter(call.data), call.data[FIELD_CODE])
            return {"status": "sent"}

        return await run_service(
            SERVICE_TEST_CODE,
            action,
            status_state=STATUS_IDLE,
            start_status_state=STATUS_SENDING,
            data=call.data,
        )

    async def generate_code(call: ServiceCall) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            protocol = call.data[FIELD_PROTOCOL]
            # Note: this parameter set is Sony SIRC-shaped. When a second
            # protocol is added, move per-protocol param assembly into the
            # ir_formats dispatcher rather than growing this block.
            params: dict[str, Any] = {
                "command": call.data[FIELD_COMMAND],
                "device": call.data[FIELD_DEVICE],
                "bits": call.data[FIELD_BITS],
                "extended": call.data[FIELD_EXTENDED],
                "repeats": call.data[FIELD_REPEATS],
                # Recorded in provenance so a saved command can be regenerated
                # even if the protocol default changes later.
                "frame_period_us": SONY_SIRC_FRAME_PERIOD_US,
            }
            carrier_override = call.data.get(FIELD_CARRIER_FREQUENCY)
            if carrier_override is not None:
                params["carrier_frequency"] = carrier_override
            try:
                signal = generate_protocol(protocol, params)
                code = zosung_encode(signal)
            except IRFormatError as err:
                raise IRLearningHubError(ERROR_CODE_GENERATION, str(err)) from err

            source = {
                "type": "protocol",
                "protocol": protocol,
                "carrier_frequency": signal.carrier_frequency,
                "params": {
                    key: value
                    for key, value in params.items()
                    if key != "carrier_frequency"
                },
            }
            return {
                "code": code,
                "format": "zosung_base64",
                "carrier_frequency": signal.carrier_frequency,
                "source": source,
            }

        return await run_service(SERVICE_GENERATE_CODE, action, data=call.data)

    async def save_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.save_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                call.data[FIELD_NAME],
                call.data[FIELD_CODE],
                call.data[FIELD_VERIFIED],
                source=call.data.get(FIELD_SOURCE),
                feature=call.data.get(FIELD_FEATURE),
            )
            return {"status": "saved"}

        return await run_service(SERVICE_SAVE_COMMAND, action, data=call.data)

    async def send_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            command = store.get_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
            )
            await adapter.async_send(transmitter(call.data), command["code"])
            return {"status": "sent"}

        return await run_service(
            SERVICE_SEND_COMMAND,
            action,
            status_state=STATUS_IDLE,
            start_status_state=STATUS_SENDING,
            data=call.data,
        )

    async def list_commands(call: ServiceCall) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            response = store.list_commands()
            for transmitter in response.get("transmitters", []):
                transmitter["entity_id"] = (
                    er.async_get(hass).async_get_entity_id(
                        Platform.INFRARED,
                        DOMAIN,
                        transmitter["key"],
                    )
                    or canonical_emitter_entity_id(transmitter["key"])
                )
            return response

        return await run_service(SERVICE_LIST_COMMANDS, action, data=call.data)

    async def add_location(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.add_location(call.data[FIELD_LOCATION_ID], call.data[FIELD_NAME])
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_LOCATION, action, data=call.data)

    async def add_device(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            transmitter_id = call.data.get(FIELD_TRANSMITTER_ID)
            await store.add_device(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_NAME],
                call.data[FIELD_TYPE],
                call.data.get(FIELD_PREFERRED_DOMAIN),
                (
                    resolve_transmitter_ref(hass, store, transmitter_id)
                    if transmitter_id
                    else None
                ),
            )
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_DEVICE, action, data=call.data)

    async def update_device(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            transmitter_id = None
            if FIELD_TRANSMITTER_ID in call.data:
                raw_transmitter_id = call.data[FIELD_TRANSMITTER_ID]
                transmitter_id = (
                    resolve_transmitter_ref(hass, store, raw_transmitter_id)
                    if raw_transmitter_id
                    else ""
                )
            await store.update_device(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                name=call.data.get(FIELD_NAME),
                device_type=call.data.get(FIELD_TYPE),
                preferred_domain=call.data.get(FIELD_PREFERRED_DOMAIN),
                transmitter_id=(
                    transmitter_id if FIELD_TRANSMITTER_ID in call.data else None
                ),
            )
            return {"status": "saved"}

        return await run_service(SERVICE_UPDATE_DEVICE, action, data=call.data)

    async def add_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.add_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                call.data[FIELD_NAME],
                call.data.get(FIELD_FEATURE),
            )
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_COMMAND, action, data=call.data)

    async def update_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.update_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                name=call.data.get(FIELD_NAME),
                icon=call.data.get(FIELD_ICON),
                feature=(
                    call.data[FIELD_FEATURE]
                    if FIELD_FEATURE in call.data
                    else None
                ),
            )
            return {"status": "saved"}

        return await run_service(SERVICE_UPDATE_COMMAND, action, data=call.data)

    async def rename_location(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.rename_location(
                call.data[FIELD_LOCATION_ID], call.data[FIELD_NAME]
            )
            return {"status": "saved"}

        return await run_service(SERVICE_RENAME_LOCATION, action, data=call.data)

    async def rename_device(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.rename_device(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_NAME],
            )
            return {"status": "saved"}

        return await run_service(SERVICE_RENAME_DEVICE, action, data=call.data)

    async def rename_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.rename_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                call.data[FIELD_NAME],
            )
            return {"status": "saved"}

        return await run_service(SERVICE_RENAME_COMMAND, action, data=call.data)

    async def delete_location(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.delete_location(
                call.data[FIELD_LOCATION_ID], call.data[FIELD_CONFIRM]
            )
            return {"status": "deleted"}

        return await run_service(SERVICE_DELETE_LOCATION, action, data=call.data)

    async def delete_device(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.delete_device(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_CONFIRM],
            )
            return {"status": "deleted"}

        return await run_service(SERVICE_DELETE_DEVICE, action, data=call.data)

    async def delete_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.delete_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
            )
            return {"status": "deleted"}

        return await run_service(SERVICE_DELETE_COMMAND, action, data=call.data)

    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARN,
        learn,
        schema=vol.Schema(
            {vol.Optional(FIELD_TIMEOUT, default=60): vol.All(int, vol.Range(min=1))}
            | OPTIONAL_TRANSMITTER
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_LAST_CODE,
        read_last_code,
        schema=vol.Schema(OPTIONAL_TRANSMITTER),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LEARN_AND_READ,
        learn_and_read,
        schema=vol.Schema(
            {
                vol.Optional(FIELD_TIMEOUT, default=60): vol.All(
                    int, vol.Range(min=1)
                ),
                vol.Optional(FIELD_POLL_INTERVAL, default=1): vol.All(
                    int, vol.Range(min=1)
                ),
            }
            | OPTIONAL_TRANSMITTER
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_CODE,
        test_code,
        schema=vol.Schema(
            {vol.Required(FIELD_CODE): _non_empty_string} | OPTIONAL_TRANSMITTER
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_CODE,
        generate_code,
        schema=vol.Schema(
            {
                vol.Required(FIELD_PROTOCOL): vol.In(list_protocols()),
                vol.Required(FIELD_COMMAND): vol.All(int, vol.Range(min=0)),
                vol.Required(FIELD_DEVICE): vol.All(int, vol.Range(min=0)),
                vol.Optional(FIELD_BITS, default=12): vol.All(
                    vol.Coerce(int), vol.In(SONY_SIRC_BITS)
                ),
                vol.Optional(FIELD_EXTENDED, default=0): vol.All(
                    int, vol.Range(min=0, max=255)
                ),
                vol.Optional(FIELD_REPEATS, default=3): vol.All(
                    int, vol.Range(min=1, max=GENERATE_MAX_REPEATS)
                ),
                vol.Optional(FIELD_CARRIER_FREQUENCY): vol.All(
                    int, vol.Range(min=1)
                ),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_COMMAND,
        save_command,
        schema=vol.Schema(
            COMMAND_SCHEMA
            | {
                vol.Required(FIELD_CODE): _non_empty_string,
                vol.Optional(FIELD_VERIFIED, default=False): cv.boolean,
                vol.Optional(FIELD_SOURCE): dict,
                vol.Optional(FIELD_FEATURE): vol.In(("",) + COMMAND_FEATURES),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        send_command,
        schema=vol.Schema(
            {
                vol.Required(FIELD_LOCATION_ID): _id_schema,
                vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                vol.Required(FIELD_COMMAND_ID): _id_schema,
            }
            | OPTIONAL_TRANSMITTER
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_COMMANDS,
        list_commands,
        schema=vol.Schema(OPTIONAL_TRANSMITTER),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_LOCATION,
        add_location,
        schema=vol.Schema(LOCATION_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_DEVICE,
        add_device,
        schema=vol.Schema(DEVICE_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_COMMAND,
        add_command,
        schema=vol.Schema(COMMAND_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_COMMAND,
        update_command,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Required(FIELD_LOCATION_ID): _id_schema,
                    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                    vol.Required(FIELD_COMMAND_ID): _id_schema,
                    vol.Optional(FIELD_NAME): _non_empty_string,
                    vol.Optional(FIELD_ICON): _icon_schema,
                    vol.Optional(FIELD_FEATURE): vol.In(("",) + COMMAND_FEATURES),
                }
            ),
            _command_update_schema,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_DEVICE,
        update_device,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Required(FIELD_LOCATION_ID): _id_schema,
                    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                    vol.Optional(FIELD_NAME): _non_empty_string,
                    vol.Optional(FIELD_TYPE): _non_empty_string,
                    vol.Optional(FIELD_PREFERRED_DOMAIN): vol.In(PREFERRED_DOMAINS),
                    vol.Optional(FIELD_TRANSMITTER_ID): _optional_string,
                }
            ),
            _device_update_schema,
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENAME_LOCATION,
        rename_location,
        schema=vol.Schema(LOCATION_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENAME_DEVICE,
        rename_device,
        schema=vol.Schema(
            {
                vol.Required(FIELD_LOCATION_ID): _id_schema,
                vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                vol.Required(FIELD_NAME): _non_empty_string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RENAME_COMMAND,
        rename_command,
        schema=vol.Schema(COMMAND_SCHEMA),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_LOCATION,
        delete_location,
        schema=vol.Schema(
            {
                vol.Required(FIELD_LOCATION_ID): _id_schema,
                vol.Required(FIELD_CONFIRM): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_DEVICE,
        delete_device,
        schema=vol.Schema(
            {
                vol.Required(FIELD_LOCATION_ID): _id_schema,
                vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                vol.Required(FIELD_CONFIRM): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_COMMAND,
        delete_command,
        schema=vol.Schema(
            {
                vol.Required(FIELD_LOCATION_ID): _id_schema,
                vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
                vol.Required(FIELD_COMMAND_ID): _id_schema,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )


def resolve_transmitter_ref(
    hass: HomeAssistant,
    store: IRRegistryStore,
    ref: str,
) -> str:
    """Resolve a transmitter reference to the canonical store key."""
    normalized = normalize_transmitter_ref(ref)
    if normalized in store.data.get("transmitters", {}):
        return normalized

    entity_entry = er.async_get(hass).async_get(ref)
    if (
        entity_entry is not None
        and entity_entry.domain == Platform.INFRARED
        and entity_entry.platform == DOMAIN
        and entity_entry.unique_id
    ):
        unique_id = str(entity_entry.unique_id)
        if unique_id in store.data.get("transmitters", {}):
            return unique_id

    raise ServiceValidationError(f"Unknown IR transmitter: {ref}")
