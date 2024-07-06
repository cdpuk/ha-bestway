"""Home Assistant entity descriptions."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BestwayUpdateCoordinator
from .bestway.model import BestwayDevice, BestwayDeviceStatus
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

        device_info = self.coordinator.api.devices[self.device_id]

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device_info.alias,
            model=device_info.device_type.value,
            manufacturer="Bestway",
        )

    @property
    def bestway_device(self) -> BestwayDevice | None:
        """Get status data for the spa providing this entity."""
        device: BestwayDevice | None = self.coordinator.api.devices.get(self.device_id)
        return device

    @property
    def status(self) -> BestwayDeviceStatus | None:
        """Get status data for the spa providing this entity."""
        status: BestwayDeviceStatus | None = self.coordinator.data.devices.get(
            self.device_id
        )
        return status

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True
        #return self.bestway_device is not None and self.bestway_device.is_online
