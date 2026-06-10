"""Config flow for IR Learning Hub."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CLUSTER_ID,
    CONF_ENDPOINT_ID,
    CONF_IEEE,
    CONF_LEARN_REASSERT_INTERVAL,
    CONF_LEARN_TIMEOUT,
    CONF_PROFILE,
    DEFAULT_CLUSTER_ID,
    DEFAULT_ENDPOINT_ID,
    DEFAULT_LEARN_REASSERT_INTERVAL,
    DEFAULT_LEARN_TIMEOUT,
    DEFAULT_PROFILE,
    DOMAIN,
)
from .storage import normalize_ieee


class IRLearningHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an IR Learning Hub config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure one ZHA IR transmitter."""
        errors: dict[str, str] = {}
        if user_input is not None:
            ieee = user_input[CONF_IEEE].strip().lower()
            await self.async_set_unique_id(normalize_ieee(ieee))
            self._abort_if_unique_id_configured()

            data = dict(user_input)
            data[CONF_IEEE] = ieee
            return self.async_create_entry(title=f"IR Learning Hub {ieee}", data=data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_IEEE, default="b0:e8:e8:ff:fe:16:ef:35"
                ): str,
                vol.Required(CONF_PROFILE, default=DEFAULT_PROFILE): vol.In(
                    ["ts1201_zosung"]
                ),
                vol.Required(CONF_ENDPOINT_ID, default=DEFAULT_ENDPOINT_ID): int,
                vol.Required(CONF_CLUSTER_ID, default=DEFAULT_CLUSTER_ID): int,
                vol.Required(CONF_LEARN_TIMEOUT, default=DEFAULT_LEARN_TIMEOUT): int,
                vol.Required(
                    CONF_LEARN_REASSERT_INTERVAL,
                    default=DEFAULT_LEARN_REASSERT_INTERVAL,
                ): int,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
