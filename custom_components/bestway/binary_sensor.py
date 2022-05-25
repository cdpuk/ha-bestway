"""Binary sensor platform."""
from __future__ import annotations

from typing import Any, Mapping

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_PROBLEM,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .const import DOMAIN
from .entity import BestwayEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []
    for device_id in coordinator.data.keys():
        entities.extend(
            [
                BestwayConnectivitySensor(coordinator, config_entry, device_id),
                BestwayErrorSensor(coordinator, config_entry, device_id),
            ]
        )

    async_add_entities(entities)


class BestwayBinarySensor(BestwayEntity, BinarySensorEntity):
    """Bestway binary sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_unique_id = f"{device_id}_{description.key}"


class BestwayConnectivitySensor(BestwayBinarySensor):
    """Sensor to indicate whether a spa is currently online."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            coordinator,
            config_entry,
            device_id,
            BinarySensorEntityDescription(
                key="connected",
                device_class=DEVICE_CLASS_CONNECTIVITY,
                entity_category=EntityCategory.DIAGNOSTIC,
                name="Spa Connected",
            ),
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is online."""
        return self.device_status is not None and self.device_status.online

    @property
    def available(self) -> bool:
        """Return True, as the connectivity sensor is always available."""
        return True


class BestwayErrorSensor(BestwayBinarySensor):
    """Sensor to indicate an error state for a spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            coordinator,
            config_entry,
            device_id,
            BinarySensorEntityDescription(
                key="has_error",
                name="Spa Errors",
                device_class=DEVICE_CLASS_PROBLEM,
            ),
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if the spa is reporting an error."""
        if not self.device_status:
            return None

        return len(self.device_status.errors) > 0 or self.device_status.earth_fault

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return more detailed error information."""
        if not self.device_status:
            return None

        errors = self.device_status.errors
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
            "gcf": self.device_status.earth_fault,
        }
