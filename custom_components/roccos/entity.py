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
        client = coordinator.client
        # Name the device by location so multiple sites are distinguishable, e.g.
        # "Rocco's Pizza - Slough" -> sensor.roccos_pizza_slough_total_spend.
        name = client.site_name or f"Rocco's Pizza ({client.hostname})"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            manufacturer="Rocco's Pizza",
            name=name,
            configuration_url=f"https://{client.hostname}/profile?view=orders",
        )
