"""Config flow for Rocco's Pizza."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import RoccosAuthError, RoccosClient, async_discover_locations
from .const import (
    CONF_HOSTNAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class RoccosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rocco's Pizza."""

    VERSION = 1

    async def _user_schema(self) -> vol.Schema:
        """Location dropdown (discovered, but a custom hostname is allowed) + credentials."""
        locations = await async_discover_locations(async_get_clientsession(self.hass))
        if locations:
            host_field = SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=h, label=l) for h, l in locations.items()],
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                    sort=True,
                )
            )
        else:
            host_field = str  # discovery failed -> plain hostname text field
        return vol.Schema(
            {
                vol.Required(CONF_HOSTNAME): host_field,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

    async def _validate(self, data: dict[str, Any]) -> tuple[RoccosClient | None, dict[str, str]]:
        """Try to log in. Returns (client, errors); client carries customer_id + site_name."""
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
        return client, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client, errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(client.customer_id)
                self._abort_if_unique_id_configured()
                site = client.site_name or "Rocco's"
                return self.async_create_entry(
                    title=f"{site} ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user", data_schema=await self._user_schema(), errors=errors
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
            _client, errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(reauth_entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )
