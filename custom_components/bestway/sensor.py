"""Home Assistant sensor descriptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN, Icon
from .coordinator import BestwayUpdateCoordinator
from .entity import BestwayEntity
from .features import VersionSensorSet, features_for
from .model import BestwayDevice, DeviceStatus


@dataclass(frozen=True, kw_only=True)
class BestwayDeviceSensorEntityDescription(SensorEntityDescription):
    """Sensor entity description for a value read from device metadata
    (`BestwayDevice`), not from polled/pushed device status.

    `name` carries a `{prefix}` placeholder filled in per-device from
    `DeviceFeatures.name_prefix` (e.g. "Spa", "Pool Filter") - it varies by
    device type, so it can't be baked into a fixed module-level constant
    the way switch.py's descriptions are.
    """

    value_fn: Callable[[BestwayDevice], StateType]


@dataclass(frozen=True, kw_only=True)
class BestwayStateSensorEntityDescription(SensorEntityDescription):
    """Sensor entity description for a value read from typed device status.

    `name` carries the same `{prefix}` placeholder as
    `BestwayDeviceSensorEntityDescription`.
    """

    value_fn: Callable[[DeviceStatus], StateType]


# V01 Gizwits devices: MCU and WiFi versions from the device object.
_GIZWITS_VERSION_SENSORS: tuple[BestwayDeviceSensorEntityDescription, ...] = (
    BestwayDeviceSensorEntityDescription(
        key="protocol_version",
        name="{prefix} Protocol Version",
        icon=Icon.PROTOCOL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.protocol_version,
    ),
    BestwayDeviceSensorEntityDescription(
        key="mcu_soft_version",
        name="{prefix} MCU Software Version",
        icon=Icon.SOFTWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.mcu_soft_version,
    ),
    BestwayDeviceSensorEntityDescription(
        key="mcu_hard_version",
        name="{prefix} MCU Hardware Version",
        icon=Icon.HARDWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.mcu_hard_version,
    ),
    BestwayDeviceSensorEntityDescription(
        key="wifi_soft_version",
        name="{prefix} Wi-Fi Software Version",
        icon=Icon.SOFTWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.wifi_soft_version,
    ),
    BestwayDeviceSensorEntityDescription(
        key="wifi_hard_version",
        name="{prefix} Wi-Fi Hardware Version",
        icon=Icon.HARDWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.wifi_hard_version,
    ),
)

# V02 devices (AWS IoT, SmartSpa): WiFi, TRD, OTA versions from shadow state.
_SHADOW_VERSION_SENSORS: tuple[BestwayStateSensorEntityDescription, ...] = (
    BestwayStateSensorEntityDescription(
        key="wifi_version",
        name="{prefix} WiFi Version",
        icon=Icon.SOFTWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.wifi_version,
    ),
    BestwayStateSensorEntityDescription(
        key="trd_version",
        name="{prefix} TRD Version",
        icon=Icon.SOFTWARE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.trd_version,
    ),
    BestwayStateSensorEntityDescription(
        key="ota_status",
        name="{prefix} OTA Status",
        icon=Icon.PROTOCOL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda status: status.ota_status,
    ),
)


def _named[
    T: (BestwayDeviceSensorEntityDescription, BestwayStateSensorEntityDescription)
](description: T, name_prefix: str) -> T:
    """Fill in a description's `{prefix}` name placeholder for one device."""
    return replace(description, name=str(description.name).format(prefix=name_prefix))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []

    for device_id, device_info in coordinator.api.devices.items():
        features = features_for(device_info, config_entry.options)
        name_prefix = features.name_prefix

        if features.version_sensors == VersionSensorSet.GIZWITS:
            entities.extend(
                DeviceSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    _named(description, name_prefix),
                )
                for description in _GIZWITS_VERSION_SENSORS
            )
        else:
            entities.extend(
                StateSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    _named(description, name_prefix),
                )
                for description in _SHADOW_VERSION_SENSORS
            )

    async_add_entities(entities)


class DeviceSensor(BestwayEntity, SensorEntity):
    """A sensor based on device metadata."""

    entity_description: BestwayDeviceSensorEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BestwayDeviceSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the relevant property."""
        if (device := self.bestway_device) is not None:
            return self.entity_description.value_fn(device)
        return None


class StateSensor(BestwayEntity, SensorEntity):
    """A sensor based on typed device status fields (for V02 devices)."""

    entity_description: BestwayStateSensorEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BestwayStateSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return value from typed device status."""
        if self.status is not None:
            return self.entity_description.value_fn(self.status)
        return None
