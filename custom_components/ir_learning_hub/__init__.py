"""IR Learning Hub integration."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Callable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    ERROR_CODE_EMPTY,
    ERROR_LEARN_TIMEOUT,
    ERROR_UNEXPECTED,
    SERVICE_ADD_COMMAND,
    SERVICE_ADD_DEVICE,
    SERVICE_ADD_LOCATION,
    SERVICE_DELETE_COMMAND,
    SERVICE_DELETE_DEVICE,
    SERVICE_DELETE_LOCATION,
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
    STATUS_CODE_RECEIVED,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_LEARNING,
    STATUS_SENDING,
)
from .errors import IRLearningHubError
from .status import HubStatus
from .storage import IRRegistryStore
from .zha_adapter import ZHAAdapter

PLATFORMS = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)
FRONTEND_URL = "/ir_learning_hub/ir-learning-hub-card.js"
FRONTEND_ICON_URL = "/ir_learning_hub/icon.png"

FIELD_CODE = "code"
FIELD_COMMAND_ID = "command_id"
FIELD_CONFIRM = "confirm"
FIELD_IR_DEVICE_ID = "ir_device_id"
FIELD_LOCATION_ID = "location_id"
FIELD_NAME = "name"
FIELD_POLL_INTERVAL = "poll_interval"
FIELD_TIMEOUT = "timeout"
FIELD_TRANSMITTER_ID = "transmitter_id"
FIELD_TYPE = "type"
FIELD_VERIFIED = "verified"
ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _id_schema(value: str) -> str:
    """Validate a stable registry ID."""
    value = cv.string(value)
    if not ID_PATTERN.fullmatch(value):
        raise vol.Invalid("ID must match [a-z0-9_]+")
    return value


OPTIONAL_TRANSMITTER = {vol.Optional(FIELD_TRANSMITTER_ID): cv.string}
LOCATION_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_NAME): cv.string,
}
DEVICE_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
    vol.Required(FIELD_NAME): cv.string,
    vol.Optional(FIELD_TYPE, default="generic"): cv.string,
}
COMMAND_SCHEMA = {
    vol.Required(FIELD_LOCATION_ID): _id_schema,
    vol.Required(FIELD_IR_DEVICE_ID): _id_schema,
    vol.Required(FIELD_COMMAND_ID): _id_schema,
    vol.Required(FIELD_NAME): cv.string,
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up IR Learning Hub from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    domain_data = hass.data[DOMAIN]

    if "store" not in domain_data:
        store = IRRegistryStore(hass)
        await store.async_load()
        domain_data["store"] = store
        domain_data["status"] = HubStatus()
        domain_data["adapter"] = ZHAAdapter(hass)
        domain_data["entries"] = set()
        domain_data["learn_tasks"] = {}

    if not domain_data.get("frontend_registered"):
        await _async_register_frontend(hass)
        domain_data["frontend_registered"] = True

    domain_data["entries"].add(entry.entry_id)
    await domain_data["store"].async_upsert_transmitter_from_entry(entry.data)

    if not domain_data.get("services_registered"):
        _register_services(hass)
        domain_data["services_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return True

    domain_data.get("entries", set()).discard(entry.entry_id)
    if domain_data.get("entries"):
        return True

    for task in domain_data.get("learn_tasks", {}).values():
        task.cancel()

    for service in (
        SERVICE_LEARN,
        SERVICE_READ_LAST_CODE,
        SERVICE_LEARN_AND_READ,
        SERVICE_TEST_CODE,
        SERVICE_SAVE_COMMAND,
        SERVICE_SEND_COMMAND,
        SERVICE_LIST_COMMANDS,
        SERVICE_ADD_LOCATION,
        SERVICE_ADD_DEVICE,
        SERVICE_ADD_COMMAND,
        SERVICE_RENAME_LOCATION,
        SERVICE_RENAME_DEVICE,
        SERVICE_RENAME_COMMAND,
        SERVICE_DELETE_LOCATION,
        SERVICE_DELETE_DEVICE,
        SERVICE_DELETE_COMMAND,
    ):
        hass.services.async_remove(DOMAIN, service)

    hass.data.pop(DOMAIN, None)
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card from the integration directory."""
    try:
        from homeassistant.components.http import StaticPathConfig

        integration_path = Path(__file__).parent
        card_path = integration_path / "www" / "ir-learning-hub-card.js"
        icon_path = integration_path / "icon.png"
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(FRONTEND_URL, str(card_path), True),
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
        return store.resolve_transmitter(data.get(FIELD_TRANSMITTER_ID))

    async def run_service(
        action: str,
        func: Callable[[], Any],
        *,
        status_state: str = STATUS_IDLE,
        data: dict[str, Any] | None = None,
    ) -> Any:
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
            status.async_set(STATUS_IDLE, action=SERVICE_LEARN)
        except asyncio.CancelledError:
            raise
        except IRLearningHubError as err:
            status.async_set(
                STATUS_ERROR,
                action=SERVICE_LEARN,
                error=err.code,
                error_message=err.message,
            )
        except Exception as err:
            status.async_set(
                STATUS_ERROR,
                action=SERVICE_LEARN,
                error=ERROR_UNEXPECTED,
                error_message=str(err),
            )

    def schedule_learn_window(tx: dict[str, Any], timeout: int) -> None:
        """Schedule background learn reassertion for one transmitter."""
        task_key = tx["ieee"]
        existing = learn_tasks.pop(task_key, None)
        if existing:
            existing.cancel()

        interval = tx["config"].get("learn_reassert_interval", 8)
        learn_tasks[task_key] = hass.async_create_task(
            keep_learning_window(tx, timeout, interval)
        )

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
            data=call.data,
        )

    async def test_code(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await adapter.async_send(transmitter(call.data), call.data[FIELD_CODE])
            return {"status": "sent"}

        return await run_service(
            SERVICE_TEST_CODE, action, status_state=STATUS_SENDING, data=call.data
        )

    async def save_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.save_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                call.data[FIELD_NAME],
                call.data[FIELD_CODE],
                call.data[FIELD_VERIFIED],
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
            SERVICE_SEND_COMMAND, action, status_state=STATUS_SENDING, data=call.data
        )

    async def list_commands(call: ServiceCall) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            return store.list_commands()

        return await run_service(SERVICE_LIST_COMMANDS, action, data=call.data)

    async def add_location(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.add_location(call.data[FIELD_LOCATION_ID], call.data[FIELD_NAME])
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_LOCATION, action, data=call.data)

    async def add_device(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.add_device(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_NAME],
                call.data[FIELD_TYPE],
            )
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_DEVICE, action, data=call.data)

    async def add_command(call: ServiceCall) -> dict[str, str]:
        async def action() -> dict[str, str]:
            await store.add_command(
                call.data[FIELD_LOCATION_ID],
                call.data[FIELD_IR_DEVICE_ID],
                call.data[FIELD_COMMAND_ID],
                call.data[FIELD_NAME],
            )
            return {"status": "saved"}

        return await run_service(SERVICE_ADD_COMMAND, action, data=call.data)

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
        schema=vol.Schema({vol.Required(FIELD_CODE): cv.string} | OPTIONAL_TRANSMITTER),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_COMMAND,
        save_command,
        schema=vol.Schema(
            COMMAND_SCHEMA
            | {
                vol.Required(FIELD_CODE): cv.string,
                vol.Optional(FIELD_VERIFIED, default=False): cv.boolean,
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
                vol.Required(FIELD_NAME): cv.string,
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
