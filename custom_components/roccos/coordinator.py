"""Data update coordinator for Rocco's Pizza orders."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RoccosApiError, RoccosAuthError, RoccosClient, is_live
from .const import DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE

_LOGGER = logging.getLogger(__name__)


class RoccosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch order history + customer record, polling faster while an order is live.

    coordinator.data = {"orders": [...newest first...], "customer": {...},
                        "item_totals": {product_name: total_quantity},
                        "deal_savings": float, "delivery_fees": float}
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RoccosClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL_IDLE,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            orders = await self.client.async_get_orders()
            customer = await self.client.async_get_customer()
            totals = await self.client.async_basket_totals(orders)
        except RoccosAuthError as err:
            # Login/re-login failed (e.g. password changed): trigger HA's reauth flow
            # so the user is prompted to re-enter credentials.
            raise ConfigEntryAuthFailed(str(err)) from err
        except RoccosApiError as err:
            raise UpdateFailed(str(err)) from err

        orders.sort(key=lambda o: o.get("CreatedTimeUtc", ""), reverse=True)

        # Speed up polling while something is in progress, slow down when idle.
        interval = SCAN_INTERVAL_ACTIVE if any(is_live(o) for o in orders) else SCAN_INTERVAL_IDLE
        if interval != self.update_interval:
            self.update_interval = interval
            _LOGGER.debug("Rocco's poll interval -> %s", interval)

        return {"orders": orders, "customer": customer, **totals}

    @property
    def orders(self) -> list[dict]:
        return (self.data or {}).get("orders", [])

    @property
    def customer(self) -> dict:
        return (self.data or {}).get("customer", {})

    @property
    def item_totals(self) -> dict[str, int]:
        return (self.data or {}).get("item_totals", {})

    @property
    def deal_savings(self) -> float:
        return (self.data or {}).get("deal_savings", 0.0)

    @property
    def latest(self) -> dict | None:
        return self.orders[0] if self.orders else None

    @property
    def live_orders(self) -> list[dict]:
        return [o for o in self.orders if is_live(o)]
