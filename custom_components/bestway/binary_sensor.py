"""Binary sensor platform."""
from __future__ import annotations

from collections.abc import Mapping

from typing import Any

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_PROBLEM,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .const import DOMAIN
from .entity import BestwayEntity, BestwaySpaEntity

_CONNECTIVITY_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="connected",
    device_class=DEVICE_CLASS_CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    name="Spa Connected",
)

_ERRORS_SENSOR_DESCRIPTION = BinarySensorEntityDescription(
    key="has_error",
    name="Spa Errors",
    device_class=DEVICE_CLASS_PROBLEM,
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
                BestwayErrorSensor(coordinator, config_entry, device_id),
            ]
        )

    async_add_entities(entities)


class SpaConnectivitySensor(BestwaySpaEntity):
    """Sensor to indicate whether a spa is currently online."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _CONNECTIVITY_SENSOR_DESCRIPTION
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
        return self.status is not None and self.status.online

    @property
    def available(self) -> bool:
        """Return True, as the connectivity sensor is always available."""
        return True


class BestwayErrorSensor(BestwaySpaEntity):
    """Sensor to indicate an error state for a spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        self.entity_description = _ERRORS_SENSOR_DESCRIPTION
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
