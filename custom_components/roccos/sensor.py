"""Sensor platform for Rocco's Pizza."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoccosConfigEntry
from .entity import RoccosEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoccosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([RoccosLatestOrderSensor(entry.runtime_data)])


class RoccosLatestOrderSensor(RoccosEntity, SensorEntity):
    """State = status of the most recent order (or 'none')."""

    _attr_translation_key = "latest_order"
    _attr_icon = "mdi:pizza"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_latest_order"

    @property
    def native_value(self) -> str:
        order = self.coordinator.latest
        return order.get("Status", "unknown") if order else "none"

    @property
    def extra_state_attributes(self) -> dict:
        order = self.coordinator.latest
        if not order:
            return {}
        return {
            "order_id": order.get("Id"),
            "placed": order.get("CreatedTimeUtc"),
            "occasion": order.get("Occasion"),
            "total": order.get("TotalAmount"),
            "currency": order.get("CurrencyCode"),
            "payment_status": order.get("PaymentStatus"),
            "live_orders": len(self.coordinator.live_orders),
        }
