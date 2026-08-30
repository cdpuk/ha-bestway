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

        device = self.coordinator.api.devices[self.device_id]

        # Build model string like reference: "AIRJET (T53NN8)" or just device type
        if device.product_series and device.product_id:
            model = f"{device.product_series} ({device.product_id})"
        elif device.product_id:
            model = device.product_id
        elif device.product_series:
            model = device.product_series
        else:
            model = device.device_type.value

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.alias,
            model=model,
            manufacturer="Bestway",
            sw_version=device.mcu_soft_version,  # Add version info
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
        """Return True if entity is available.

        Note: is_online from the Bestway/Gizwits API is unreliable and
        frequently returns false even when the device is functioning and
        controllable via the app. The API continues to return valid state
        data regardless of this flag. We therefore only check that the
        coordinator has data and the device is known.

        See: https://github.com/cdpuk/ha-bestway/issues/89
        See: https://github.com/cdpuk/ha-bestway/issues/93
        See: https://github.com/cdpuk/ha-bestway/issues/100
        """
        return self.coordinator.last_update_success and self.bestway_device is not None
