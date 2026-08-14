"""Config flow for Rocco's Pizza."""
from __future__ import annotations

import logging
from collections.abc import Mapping
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

    async def _validate(self, data: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
        """Try to log in. Returns (customer_id, errors)."""
        client = RoccosClient(
            async_get_clientsession(self.hass),
            data[CONF_HOSTNAME],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        try:
            await client.async_validate()
        except RoccosAuthError:
            return None, {"base": "invalid_auth"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Rocco's login")
            return None, {"base": "cannot_connect"}
        return client.customer_id, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            customer_id, errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(customer_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Rocco's ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered by ConfigEntryAuthFailed when a re-login fails at runtime."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            # Reauth only changes the password; the username (and therefore the
            # account) is fixed, so the login always maps to the same customer.
            data = {**reauth_entry.data, **user_input}
            _customer_id, errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(reauth_entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )
