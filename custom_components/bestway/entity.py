"""Home Assistant entity descriptions."""
from __future__ import annotations
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BestwayUpdateCoordinator
from .bestway import BestwayDevice, BestwayDeviceReport, BestwayDeviceStatus
from .const import DOMAIN


class BestwayEntity(CoordinatorEntity[BestwayUpdateCoordinator]):
    """Bestway base entity type."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.device_id = device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Device information for the spa providing this entity."""

        device_info: BestwayDevice = self.coordinator.data[self.device_id].device

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device_info.alias,
            model=device_info.product_name,
            manufacturer="Bestway",
        )

    @property
    def device_status(self) -> BestwayDeviceStatus | None:
        """Get status data for the spa providing this entity."""
        device_report: BestwayDeviceReport = self.coordinator.data.get(self.device_id)
        if device_report:
            return device_report.status
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device_status is not None and self.device_status.online
