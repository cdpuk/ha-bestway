"""Home Assistant sensor descriptions."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from custom_components.bestway.bestway import BestwayDevice

from . import BestwayUpdateCoordinator
from .const import DOMAIN, Icon
from .entity import BestwayEntity


@dataclass
class DeviceSensorDescription:
    """An entity description with a function that describes how to derive a value."""

    entity_description: SensorEntityDescription
    value_fn: Callable[[BestwayDevice], StateType]


_PROTOCOL_VERSION_SENSOR = DeviceSensorDescription(
    SensorEntityDescription(
        key="protocol_version",
        name="Protocol Version",
        icon=Icon.PROTOCOL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    lambda device: device.protocol_version,
)

_MCU_SOFTWARE_VERSION_SENSOR = DeviceSensorDescription(
    SensorEntityDescription(
        key="mcu_soft_version",
        name="MCU Software Version",
        icon=Icon.SOFTWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    lambda device: device.mcu_soft_version,
)

_MCU_HARDWARE_VERSION_SENSOR = DeviceSensorDescription(
    SensorEntityDescription(
        key="mcu_hard_version",
        name="MCU Hardware Version",
        icon=Icon.HARDWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    lambda device: device.mcu_hard_version,
)

_WIFI_HARDWARE_VERSION_SENSOR = DeviceSensorDescription(
    SensorEntityDescription(
        key="wifi_soft_version",
        name="Wi-Fi Hardware Version",
        icon=Icon.HARDWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    lambda device: device.wifi_soft_version,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []
    for device_id in coordinator.data.keys():
        entities.extend(
            [
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=_PROTOCOL_VERSION_SENSOR,
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=_MCU_SOFTWARE_VERSION_SENSOR,
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=_MCU_HARDWARE_VERSION_SENSOR,
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=_WIFI_HARDWARE_VERSION_SENSOR,
                ),
            ]
        )

    async_add_entities(entities)


class DeviceSensor(BestwayEntity, SensorEntity):
    """A sensor based on device metadata."""

    sensor_description: DeviceSensorDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        sensor_description: DeviceSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, device_id)
        self.sensor_description = sensor_description
        self.entity_description = sensor_description.entity_description
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the relevant property."""
        if (device := self.bestway_device) is not None:
            return self.sensor_description.value_fn(device)
