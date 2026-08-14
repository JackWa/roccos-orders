"""Base entity for Rocco's Pizza."""
from __future__ import annotations

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RoccosCoordinator


class RoccosEntity(CoordinatorEntity[RoccosCoordinator]):
    """Shared device grouping / attribution for all Rocco's entities."""

    _attr_has_entity_name = True
    _attr_attribution = "Data from roccospizza.co.uk (unofficial)"

    def __init__(self, coordinator: RoccosCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            manufacturer="Rocco's Pizza",
            name="Rocco's Pizza",
            configuration_url=f"https://{coordinator.client.hostname}/profile?view=orders",
        )
