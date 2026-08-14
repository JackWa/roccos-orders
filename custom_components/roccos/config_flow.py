"""Config flow for Rocco's Pizza."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoccosAuthError, RoccosClient
from .const import (
    CONF_HOSTNAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_HOSTNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_HOSTNAME, default=DEFAULT_HOSTNAME): str,
    }
)


class RoccosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rocco's Pizza."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = RoccosClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOSTNAME],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_validate()
            except RoccosAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Rocco's login")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(client.customer_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Rocco's ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
