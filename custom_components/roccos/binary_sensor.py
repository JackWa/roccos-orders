"""Binary sensor platform for Rocco's Pizza."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoccosConfigEntry
from .entity import RoccosEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoccosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([RoccosOrderActiveBinarySensor(entry.runtime_data)])


class RoccosOrderActiveBinarySensor(RoccosEntity, BinarySensorEntity):
    """On while any order is in progress — the entity automations key off."""

    _attr_translation_key = "order_active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:moped"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_order_active"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.live_orders)

    @property
    def extra_state_attributes(self) -> dict:
        live = self.coordinator.live_orders
        return {
            "count": len(live),
            "statuses": [o.get("Status") for o in live],
            "order_ids": [o.get("Id") for o in live],
        }
