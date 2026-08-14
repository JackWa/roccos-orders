"""The Rocco's Pizza integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoccosClient
from .const import CONF_HOSTNAME, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import RoccosCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type RoccosConfigEntry = ConfigEntry[RoccosCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: RoccosConfigEntry) -> bool:
    """Set up Rocco's Pizza from a config entry."""
    client = RoccosClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOSTNAME],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = RoccosCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RoccosConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
