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
from .const import DOMAIN, Icon
from .entity import BestwayEntity, BestwayPoolFilterEntity, BestwaySpaEntity

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

    for device_id in coordinator.data.spa_devices.keys():
        entities.extend(
            [
                SpaConnectivitySensor(coordinator, config_entry, device_id),
                SpaErrorsSensor(coordinator, config_entry, device_id),
            ]
        )
    for device_id in coordinator.data.pool_filter_devices.keys():
        entities.extend(
            [
                PoolFilterConnectivitySensor(coordinator, config_entry, device_id),
                PoolFilterChangeRequiredSensor(coordinator, config_entry, device_id),
                PoolFilterErrorSensor(coordinator, config_entry, device_id),
            ]
        )

    async_add_entities(entities)


class SpaConnectivitySensor(BestwaySpaEntity, BinarySensorEntity):
    """Sensor to indicate whether a spa is currently online."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _SPA_CONNECTIVITY_SENSOR_DESCRIPTION
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
        return self.status is not None and self.status.online

    @property
    def available(self) -> bool:
        """Return True, as the connectivity sensor is always available."""
        return True


class SpaErrorsSensor(BestwaySpaEntity, BinarySensorEntity):
    """Sensor to indicate an error state for a spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _SPA_ERRORS_SENSOR_DESCRIPTION
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

        return len(self.status.errors) > 0 or self.status.earth_fault

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return more detailed error information."""
        if not self.status:
            return None

        errors = self.status.errors
        return {
            "e01": 1 in errors,
            "e02": 2 in errors,
            "e03": 3 in errors,
            "e04": 4 in errors,
            "e05": 5 in errors,
            "e06": 6 in errors,
            "e07": 7 in errors,
            "e08": 8 in errors,
            "e09": 9 in errors,
            "gcf": self.status.earth_fault,
        }


class PoolFilterConnectivitySensor(BestwayPoolFilterEntity, BinarySensorEntity):
    """Sensor to indicate whether a pool filter is currently online."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _POOL_FILTER_CONNECTIVITY_SENSOR_DESCRIPTION
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        super().__init__(
            coordinator,
            config_entry,
            device_id,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the pool filter is online."""
        return self.status is not None and self.status.online

    @property
    def available(self) -> bool:
        """Return True, as the connectivity sensor is always available."""
        return True


class PoolFilterChangeRequiredSensor(BestwayPoolFilterEntity, BinarySensorEntity):
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
        return self.status is not None and self.status.filter_change_required


class PoolFilterErrorSensor(BestwayPoolFilterEntity, BinarySensorEntity):
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
        return self.status is not None and self.status.error
