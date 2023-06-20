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
from .bestway.model import BestwayPoolFilterDeviceStatus, BestwaySpaDeviceStatus
from .const import DOMAIN, Icon
from .entity import BestwayEntity, BestwayPoolFilterEntity, BestwaySpaEntity


@dataclass
class SpaSwitchFunctionsMixin:
    """Functions for spa devices."""

    value_fn: Callable[[BestwaySpaDeviceStatus], bool]
    turn_on_fn: Callable[[BestwayApi, str], Awaitable[None]]
    turn_off_fn: Callable[[BestwayApi, str], Awaitable[None]]


@dataclass
class PoolFilterSwitchFunctionsMixin:
    """Functions for pool filter devices."""

    value_fn: Callable[[BestwayPoolFilterDeviceStatus], bool]
    turn_on_fn: Callable[[BestwayApi, str], Awaitable[None]]
    turn_off_fn: Callable[[BestwayApi, str], Awaitable[None]]


@dataclass
class SpaSwitchEntityDescription(SwitchEntityDescription, SpaSwitchFunctionsMixin):
    """Entity description for bestway spa switches."""


@dataclass
class PoolFilterSwitchEntityDescription(
    SwitchEntityDescription, PoolFilterSwitchFunctionsMixin
):
    """Entity description for bestway pool filter switches."""


_SPA_SWITCH_TYPES = [
    SpaSwitchEntityDescription(
        key="spa_filter_power",
        name="Spa Filter",
        icon=Icon.FILTER,
        value_fn=lambda s: s.filter_power,
        turn_on_fn=lambda api, device_id: api.spa_set_filter(device_id, True),
        turn_off_fn=lambda api, device_id: api.spa_set_filter(device_id, False),
    ),
    SpaSwitchEntityDescription(
        key="spa_wave_power",
        name="Spa Bubbles",
        icon=Icon.BUBBLES,
        value_fn=lambda s: s.wave_power,
        turn_on_fn=lambda api, device_id: api.spa_set_bubbles(device_id, True),
        turn_off_fn=lambda api, device_id: api.spa_set_bubbles(device_id, False),
    ),
    SpaSwitchEntityDescription(
        key="spa_locked",
        name="Spa Locked",
        icon=Icon.LOCK,
        value_fn=lambda s: s.locked,
        turn_on_fn=lambda api, device_id: api.spa_set_locked(device_id, True),
        turn_off_fn=lambda api, device_id: api.spa_set_locked(device_id, False),
    ),
]

_POOL_FILTER_SWITCH_TYPES = [
    PoolFilterSwitchEntityDescription(
        key="pool_filter_power",
        name="Pool Filter Power",
        icon=Icon.FILTER,
        value_fn=lambda s: s.power,
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
    entities.extend(
        SpaSwitch(coordinator, config_entry, device_id, description)
        for device_id in coordinator.data.spa_devices.keys()
        for description in _SPA_SWITCH_TYPES
    )
    entities.extend(
        PoolFilterSwitch(coordinator, config_entry, device_id, description)
        for device_id in coordinator.data.pool_filter_devices.keys()
        for description in _POOL_FILTER_SWITCH_TYPES
    )
    async_add_entities(entities)


class SpaSwitch(BestwaySpaEntity, SwitchEntity):
    """Bestway switch entity for spa devices."""

    entity_description: SpaSwitchEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: SpaSwitchEntityDescription,
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


class PoolFilterSwitch(BestwayPoolFilterEntity, SwitchEntity):
    """Bestway switch entity for pool filter devices."""

    entity_description: PoolFilterSwitchEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: PoolFilterSwitchEntityDescription,
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
