"""Switch platform support."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .bestway.api import BestwayApi
from .bestway.model import BestwayDeviceStatus, BestwayDeviceType
from .const import DOMAIN, Icon
from .entity import BestwayEntity


@dataclass(frozen=True)
class SwitchFunctionsMixin:
    """Functions for spa devices."""

    value_fn: Callable[[BestwayDeviceStatus], bool]
    turn_on_fn: Callable[[BestwayApi, str], Awaitable[None]]
    turn_off_fn: Callable[[BestwayApi, str], Awaitable[None]]


@dataclass(frozen=True)
class BestwaySwitchEntityDescription(SwitchEntityDescription, SwitchFunctionsMixin):
    """Entity description for bestway spa switches."""


_AIRJET_SPA_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_power",
    name="Spa Power",
    icon=Icon.POWER,
    value_fn=lambda s: bool(s.attrs["power"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_power(device_id, False),
)

_AIRJET_SPA_FILTER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_filter_power",
    name="Spa Filter",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.attrs["filter_power"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_filter(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_filter(device_id, False),
)

_AIRJET_WAVE_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_wave_power",
    name="Spa Bubbles",
    icon=Icon.BUBBLES,
    value_fn=lambda s: bool(s.attrs["wave_power"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_bubbles(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_bubbles(device_id, False),
)

_AIRJET_LOCK_SWITCH = BestwaySwitchEntityDescription(
    key="spa_locked",
    name="Spa Locked",
    icon=Icon.LOCK,
    value_fn=lambda s: bool(s.attrs["locked"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_locked(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_locked(device_id, False),
)

_HYDROJET_SPA_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_power",
    name="Spa Power",
    icon=Icon.POWER,
    value_fn=lambda s: bool(s.attrs["power"]),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_power(device_id, False),
)

_HYDROJET_SPA_FILTER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_filter_power",
    name="Spa Filter",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.attrs["filter"] == 2),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_filter(device_id, True),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_filter(device_id, False),
)

_HYDROJET_LOCK_SWITCH = BestwaySwitchEntityDescription(
    key="spa_locked",
    name="Spa Locked",
    icon=Icon.LOCK,
    value_fn=lambda s: bool(s.attrs["bit6"]),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_locked(device_id, True),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_locked(device_id, False),
)

_POOL_FILTER_SWITCH_TYPES = [
    BestwaySwitchEntityDescription(
        key="pool_filter_power",
        name="Pool Filter Power",
        icon=Icon.FILTER,
        value_fn=lambda s: bool(s.attrs["power"]),
        turn_on_fn=lambda api, device_id: api.pool_filter_set_power(device_id, True),
        turn_off_fn=lambda api, device_id: api.pool_filter_set_power(device_id, False),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        if device.device_type == BestwayDeviceType.AIRJET_SPA:
            entities.extend(
                [
                    SpaSwitch(
                        coordinator, config_entry, device_id, _AIRJET_SPA_POWER_SWITCH
                    ),
                    SpaSwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_SPA_FILTER_SWITCH,
                    ),
                    SpaSwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_LOCK_SWITCH,
                    ),
                    SpaSwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_WAVE_POWER_SWITCH,
                    ),
                ]
            )

        if device.device_type in [
            BestwayDeviceType.HYDROJET_PRO_SPA,
            BestwayDeviceType.AIRJET_V01_SPA,
        ]:
            entities.extend(
                [
                    SpaSwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _HYDROJET_SPA_POWER_SWITCH,
                    ),
                    SpaSwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _HYDROJET_SPA_FILTER_SWITCH,
                    ),
                ]
            )

        if device.device_type == BestwayDeviceType.POOL_FILTER:
            entities.extend(
                PoolFilterSwitch(coordinator, config_entry, device_id, description)
                for description in _POOL_FILTER_SWITCH_TYPES
            )

    async_add_entities(entities)


class SpaSwitch(BestwayEntity, SwitchEntity):
    """Bestway switch entity for spa devices."""

    entity_description: BestwaySwitchEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BestwaySwitchEntityDescription,
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if status := self.status:
            return self.entity_description.value_fn(status)

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.entity_description.turn_on_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.entity_description.turn_off_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_refresh()


class PoolFilterSwitch(BestwayEntity, SwitchEntity):
    """Bestway switch entity for pool filter devices."""

    entity_description: BestwaySwitchEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BestwaySwitchEntityDescription,
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if status := self.status:
            return self.entity_description.value_fn(status)

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.entity_description.turn_on_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.entity_description.turn_off_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_refresh()
