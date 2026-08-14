"""Data update coordinator for Rocco's Pizza orders."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RoccosApiError, RoccosClient, is_live
from .const import DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE

_LOGGER = logging.getLogger(__name__)


class RoccosCoordinator(DataUpdateCoordinator[list[dict]]):
    """Fetch order history, polling faster while an order is live."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RoccosClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL_IDLE,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> list[dict]:
        try:
            orders = await self.client.async_get_orders()
        except RoccosApiError as err:
            raise UpdateFailed(str(err)) from err

        orders.sort(key=lambda o: o.get("CreatedTimeUtc", ""), reverse=True)

        # Speed up polling while something is in progress, slow down when idle.
        interval = SCAN_INTERVAL_ACTIVE if any(is_live(o) for o in orders) else SCAN_INTERVAL_IDLE
        if interval != self.update_interval:
            self.update_interval = interval
            _LOGGER.debug("Rocco's poll interval -> %s", interval)

        return orders

    @property
    def latest(self) -> dict | None:
        return self.data[0] if self.data else None

    @property
    def live_orders(self) -> list[dict]:
        return [o for o in (self.data or []) if is_live(o)]
