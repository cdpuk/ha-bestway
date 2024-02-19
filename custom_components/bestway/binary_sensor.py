"""Binary sensor platform."""

from __future__ import annotations

from collections.abc import Mapping

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

_AIRJET_SPA_ERRORS_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
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
        if device.device_type == BestwayDeviceType.AIRJET_SPA:
            entities.extend(
                [
                    DeviceConnectivitySensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
                    ),
                    AirjetSpaErrorsSensor(coordinator, config_entry, device_id),
                ]
            )

        if device.device_type == BestwayDeviceType.AIRJET_V01_SPA:
            entities.extend(
                [
                    DeviceConnectivitySensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
                    )
                ]
            )

        if device.device_type in [
            BestwayDeviceType.HYDROJET_SPA,
            BestwayDeviceType.HYDROJET_PRO,
        ]:
            entities.extend(
                [
                    DeviceConnectivitySensor(
                        coordinator,
                        config_entry,
                        device_id,
                        _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
                    ),
                    HydrojetSpaErrorsSensor(coordinator, config_entry, device_id),
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
                    PoolFilterErrorSensor(coordinator, config_entry, device_id),
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


class AirjetSpaErrorsSensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate an error state for an Airjet spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _AIRJET_SPA_ERRORS_SENSOR_DESCRIPTION
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is reporting an error."""
        if not self.status:
            return None

        errors = []
        for err_num in range(1, 10):
            if self.status.attrs[f"system_err{err_num}"] == 1:
                errors.append(err_num)

        return len(errors) > 0 or self.status.attrs["earth"]

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return more detailed error information."""
        if not self.status:
            return None

        return {
            "e01": self.status.attrs["system_err1"],
            "e02": self.status.attrs["system_err2"],
            "e03": self.status.attrs["system_err3"],
            "e04": self.status.attrs["system_err4"],
            "e05": self.status.attrs["system_err5"],
            "e06": self.status.attrs["system_err6"],
            "e07": self.status.attrs["system_err7"],
            "e08": self.status.attrs["system_err8"],
            "e09": self.status.attrs["system_err9"],
            "gcf": self.status.attrs["earth"],
        }


class HydrojetSpaErrorsSensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate an error state for a Hydrojet spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _AIRJET_SPA_ERRORS_SENSOR_DESCRIPTION
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is reporting an error."""
        if not self.status:
            return None

        errors = []
        for err_num in [1,2,3,4,5,8,9,12,13]:
            if self.status.attrs[f"E{str(err_num).zfill(2)}"] == 1:
                errors.append(err_num)

        return len(errors) > 0 or self.status.attrs.get("earth")

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return more detailed error information."""
        if not self.status:
            return None

        # Only return errors listed in the instruction manual.
        return {
            "e01": self.status.attrs["E01"],
            "e02": self.status.attrs["E02"],
            "e03": self.status.attrs["E03"],
            "e04": self.status.attrs["E04"],
            "e05": self.status.attrs["E05"],
            "e08": self.status.attrs["E08"],
            "e09": self.status.attrs["E09"],
            "e12": self.status.attrs["E12"],
            "e13": self.status.attrs["E13"],
            "gcf": self.status.attrs.get("earth"), # not always present
        }


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


class PoolFilterErrorSensor(BestwayEntity, BinarySensorEntity):
    """Sensor to indicate an error state for a pool filter."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _POOL_FILTER_ERROR_SENSOR_DESCRIPTION
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the pool filter is reporting an error."""
        return self.status is not None and self.status.attrs["error"]
