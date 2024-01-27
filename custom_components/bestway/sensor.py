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

from . import BestwayUpdateCoordinator
from .bestway.model import BestwayDevice, BestwayDeviceType
from .const import DOMAIN, Icon
from .entity import BestwayEntity


@dataclass
class DeviceSensorDescription:
    """An entity description with a function that describes how to derive a value."""

    entity_description: SensorEntityDescription
    value_fn: Callable[[BestwayDevice], StateType]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []

    for device_id, device_info in coordinator.api.devices.items():
        name_prefix = "Bestway"
        if device_info.device_type in [
            BestwayDeviceType.AIRJET_SPA,
            BestwayDeviceType.HYDROJET_SPA,
        ]:
            name_prefix = "Spa"
        elif device_info.device_type == BestwayDeviceType.POOL_FILTER:
            name_prefix = "Pool Filter"

        entities.extend(
            [
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=DeviceSensorDescription(
                        SensorEntityDescription(
                            key="protocol_version",
                            name=f"{name_prefix} Protocol Version",
                            icon=Icon.PROTOCOL,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        ),
                        lambda device: device.protocol_version,
                    ),
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=DeviceSensorDescription(
                        SensorEntityDescription(
                            key="mcu_soft_version",
                            name=f"{name_prefix} MCU Software Version",
                            icon=Icon.SOFTWARE,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        ),
                        lambda device: device.mcu_soft_version,
                    ),
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=DeviceSensorDescription(
                        SensorEntityDescription(
                            key="mcu_hard_version",
                            name=f"{name_prefix} MCU Hardware Version",
                            icon=Icon.HARDWARE,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        ),
                        lambda device: device.mcu_hard_version,
                    ),
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=DeviceSensorDescription(
                        SensorEntityDescription(
                            key="wifi_soft_version",
                            name=f"{name_prefix} Wi-Fi Software Version",
                            icon=Icon.SOFTWARE,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        ),
                        lambda device: device.wifi_soft_version,
                    ),
                ),
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    sensor_description=DeviceSensorDescription(
                        SensorEntityDescription(
                            key="wifi_hard_version",
                            name=f"{name_prefix} Wi-Fi Hardware Version",
                            icon=Icon.HARDWARE,
                            entity_category=EntityCategory.DIAGNOSTIC,
                        ),
                        lambda device: device.wifi_hard_version,
                    ),
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
        return None
