"""Sensor platform for Rocco's Pizza."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import RoccosConfigEntry
from .api import is_live
from .entity import RoccosEntity

# How many recent orders / top items to expose as attributes.
RECENT_LIMIT = 10
TOP_ITEMS = 10


def _compact(order: dict) -> dict:
    """Trim an order to the fields worth exposing as attribute data."""
    return {
        "order_id": order.get("Id"),
        "status": order.get("Status"),
        "placed": order.get("CreatedTimeUtc"),
        "occasion": order.get("Occasion"),
        "total": order.get("TotalAmount"),
        "currency": order.get("CurrencyCode"),
        "live": is_live(order),
    }


def _real_addresses(customer: dict) -> list[dict]:
    """Contacts that hold an actual address — excludes the blank 'add new address'
    placeholder (AddressLine1 like '--')."""
    return [
        c for c in (customer.get("Contacts") or [])
        if (c.get("AddressLine1") or "").strip(" -")
    ]


def _default_address(customer: dict) -> dict | None:
    """The default real address, else the first real one."""
    real = _real_addresses(customer)
    for contact in real:
        if contact.get("IsDefault"):
            return contact
    return real[0] if real else None


def _format_address(contact: dict) -> str:
    parts = [
        contact.get("AddressLine1"),
        contact.get("AddressLine2"),
        contact.get("Town"),
        contact.get("PostCode"),
    ]
    return ", ".join(p for p in parts if p and p.strip(" -"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RoccosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            RoccosLatestOrderSensor(coordinator),
            RoccosOrderCountSensor(coordinator),
            RoccosLastOrderTotalSensor(coordinator),
            RoccosLastOrderPlacedSensor(coordinator),
            RoccosTotalSpendSensor(coordinator),
            RoccosAverageOrderValueSensor(coordinator),
            RoccosTotalDealSavingsSensor(coordinator),
            RoccosMostOrderedItemSensor(coordinator),
            RoccosFavouriteOccasionSensor(coordinator),
            RoccosLoyaltyPointsSensor(coordinator),
            RoccosAccountSensor(coordinator),
        ]
    )


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
        recent = [_compact(o) for o in self.coordinator.orders[:RECENT_LIMIT]]
        if not order:
            return {"live_orders": 0, "recent_orders": recent}
        return {
            "order_id": order.get("Id"),
            "placed": order.get("CreatedTimeUtc"),
            "occasion": order.get("Occasion"),
            "total": order.get("TotalAmount"),
            "currency": order.get("CurrencyCode"),
            "payment_status": order.get("PaymentStatus"),
            "live_orders": len(self.coordinator.live_orders),
            "recent_orders": recent,
        }


class RoccosOrderCountSensor(RoccosEntity, SensorEntity):
    """State = total number of orders on the account."""

    _attr_translation_key = "order_count"
    _attr_icon = "mdi:receipt-text"
    _attr_native_unit_of_measurement = "orders"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_order_count"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.orders)

    @property
    def extra_state_attributes(self) -> dict:
        live = len(self.coordinator.live_orders)
        return {"live": live, "completed": len(self.coordinator.orders) - live}


class RoccosLastOrderTotalSensor(RoccosEntity, SensorEntity):
    """State = £ total of the most recent order."""

    _attr_translation_key = "last_order_total"
    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_order_total"

    @property
    def native_value(self) -> float | None:
        order = self.coordinator.latest
        return order.get("TotalAmount") if order else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        order = self.coordinator.latest
        return order.get("CurrencyCode", "GBP") if order else None


class RoccosLastOrderPlacedSensor(RoccosEntity, SensorEntity):
    """State = timestamp the most recent order was placed."""

    _attr_translation_key = "last_order_placed"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_order_placed"

    @property
    def native_value(self) -> datetime | None:
        order = self.coordinator.latest
        if not order or not order.get("CreatedTimeUtc"):
            return None
        return dt_util.parse_datetime(order["CreatedTimeUtc"])


class RoccosTotalSpendSensor(RoccosEntity, SensorEntity):
    """State = sum of every order's total (lifetime spend)."""

    _attr_translation_key = "total_spend"
    _attr_icon = "mdi:cash-multiple"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_total_spend"

    @property
    def native_value(self) -> float:
        total = sum(float(o.get("TotalAmount") or 0) for o in self.coordinator.orders)
        return round(total, 2)


class RoccosAverageOrderValueSensor(RoccosEntity, SensorEntity):
    """State = mean order value (lifetime spend / order count)."""

    _attr_translation_key = "average_order_value"
    _attr_icon = "mdi:cash-100"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_average_order_value"

    @property
    def native_value(self) -> float | None:
        orders = self.coordinator.orders
        if not orders:
            return None
        total = sum(float(o.get("TotalAmount") or 0) for o in orders)
        return round(total / len(orders), 2)


class RoccosTotalDealSavingsSensor(RoccosEntity, SensorEntity):
    """State = lifetime £ saved via deals (sum of basket DealSavingAmount)."""

    _attr_translation_key = "total_deal_savings"
    _attr_icon = "mdi:tag-heart"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "GBP"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_total_deal_savings"

    @property
    def native_value(self) -> float:
        return self.coordinator.deal_savings


class RoccosFavouriteOccasionSensor(RoccosEntity, SensorEntity):
    """State = your most common occasion (Delivery / Collection)."""

    _attr_translation_key = "favourite_occasion"
    _attr_icon = "mdi:moped-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_favourite_occasion"

    def _counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self.coordinator.orders:
            occ = order.get("Occasion") or "Unknown"
            counts[occ] = counts.get(occ, 0) + 1
        return counts

    @property
    def native_value(self) -> str | None:
        counts = self._counts()
        return max(counts, key=counts.get) if counts else None

    @property
    def extra_state_attributes(self) -> dict:
        return {k.lower(): v for k, v in self._counts().items()}


class RoccosLoyaltyPointsSensor(RoccosEntity, SensorEntity):
    """State = loyalty points balance.

    Note: Rocco's loyalty scheme is not active at every site (e.g. Hythe), where
    this stays 0 — that is the API's own value, not a bug.
    """

    _attr_translation_key = "loyalty_points"
    _attr_icon = "mdi:star-circle"
    _attr_native_unit_of_measurement = "points"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_loyalty_points"

    @property
    def native_value(self) -> int:
        return (self.coordinator.customer.get("LoyaltyState") or {}).get("PointsBalance", 0)


class RoccosMostOrderedItemSensor(RoccosEntity, SensorEntity):
    """State = the product you've ordered most (by total quantity)."""

    _attr_translation_key = "most_ordered_item"
    _attr_icon = "mdi:trophy"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_most_ordered_item"

    def _ranked(self) -> list[tuple[str, int]]:
        return sorted(
            self.coordinator.item_totals.items(), key=lambda kv: kv[1], reverse=True
        )

    @property
    def native_value(self) -> str | None:
        ranked = self._ranked()
        return ranked[0][0] if ranked else None

    @property
    def extra_state_attributes(self) -> dict:
        ranked = self._ranked()
        return {
            "quantity": ranked[0][1] if ranked else 0,
            "top_items": [{"item": n, "quantity": q} for n, q in ranked[:TOP_ITEMS]],
        }


class RoccosAccountSensor(RoccosEntity, SensorEntity):
    """Account details (from ?view=account / ?view=address): name, email, address."""

    _attr_translation_key = "account"
    _attr_icon = "mdi:account"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_account"

    @property
    def native_value(self) -> str | None:
        c = self.coordinator.customer
        name = " ".join(p for p in (c.get("FirstName"), c.get("LastName")) if p)
        return name or c.get("Email") or None

    @property
    def extra_state_attributes(self) -> dict:
        c = self.coordinator.customer
        default = _default_address(c)
        return {
            "email": c.get("Email"),
            "default_address": _format_address(default) if default else None,
            "address_count": len(_real_addresses(c)),  # excludes the blank placeholder
        }
