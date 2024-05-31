"""Binary sensor platform."""

from __future__ import annotations

from collections.abc import Mapping
import re

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .bestway.model import BestwayDeviceType
from .const import DOMAIN, Icon
from .entity import BestwayEntity

_SPA_CONNECTIVITY_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="spa_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    name="Spa Connected",
)

_SPA_ERRORS_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="spa_has_error",
    name="Spa Errors",
    device_class=BinarySensorDeviceClass.PROBLEM,
)

_POOL_FILTER_CONNECTIVITY_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="pool_filter_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    name="Pool Filter Connected",
)

_POOL_FILTER_CHANGE_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="pool_filter_change_required",
    name="Pool Filter Change Required",
    icon=Icon.FILTER,
)

_POOL_FILTER_ERROR_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="pool_filter_has_error",
    name="Pool Filter Errors",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        if device.device_type in [
            BestwayDeviceType.AIRJET_SPA,
            BestwayDeviceType.AIRJET_V01_SPA,
            BestwayDeviceType.HYDROJET_SPA,
            BestwayDeviceType.HYDROJET_PRO_SPA,
        ]:
            entities.extend(
                [
                    DeviceConnectivitySensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
                    ),
                    DeviceErrorsSensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _SPA_ERRORS_SENSOR_DESCRIPTION,
                    ),
                ]
            )

        if device.device_type == BestwayDeviceType.POOL_FILTER:
            entities.extend(
                [
                    DeviceConnectivitySensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _POOL_FILTER_CONNECTIVITY_SENSOR_DESCRIPTION,
                    ),
                    PoolFilterChangeRequiredSensor(
                        coordinator, config_entry, device_id
                    ),
                    DeviceErrorsSensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _POOL_FILTER_ERROR_SENSOR_DESCRIPTION,
                    ),
                ]
            )

    async_add_entities(entities)


class DeviceConnectivitySensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate whether a device is currently online."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = entity_description
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the spa is online."""
        return self.bestway_device is not None and self.bestway_device.is_online

    @property
    def available(self) -> bool:
        """Return True, as the connectivity sensor is always available."""
        return True


class DeviceErrorsSensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate an error state for all device types."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = entity_description
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    def _all_error_properties(self) -> dict[str, bool]:
        """Get all error properties from the device status."""
        errors: dict[str, bool] = {}

        if not self.status:
            return errors

        # Airjet error properties
        for attr in self.status.attrs:
            if re.match("system_err\\d+", attr):
                errors[attr] = bool(self.status.attrs[attr])

        # Airjet ground fault
        if "earth" in self.status.attrs:
            errors["earth"] = bool(self.status.attrs["earth"])

        # Airjet_V01 and Hydrojet
        for attr in self.status.attrs:
            if re.match("E\\d{2}", attr):
                errors[attr] = bool(self.status.attrs[attr])

        # Pool filter
        if "error" in self.status.attrs:
            errors["error"] = bool(self.status.attrs["error"])

        return errors

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is reporting an error."""
        errors = self._all_error_properties()
        active_errors = {k: v for k, v in errors.items() if v}
        return len(active_errors) > 0

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return more detailed error information."""
        return self._all_error_properties()


class PoolFilterChangeRequiredSensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate whether a pool filter requires a change."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _POOL_FILTER_CHANGE_SENSOR_DESCRIPTION
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is online."""
        return self.status is not None and self.status.attrs["filter"]
