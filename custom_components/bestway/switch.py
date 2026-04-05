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
from .aws_iot.api import AwsIotApi
from .bestway.api import BestwayApi
from .bestway.model import BestwayDeviceStatus, BestwayDeviceType, HydrojetFilter
from .const import DOMAIN, Icon
from .entity import BestwayEntity


@dataclass(frozen=True, kw_only=True)
class BestwaySwitchEntityDescription(SwitchEntityDescription):
    """Entity description for bestway spa switches."""

    value_fn: Callable[[BestwayDeviceStatus], bool]
    turn_on_fn: Callable[[BestwayApi | AwsIotApi, str], Awaitable[None]]
    turn_off_fn: Callable[[BestwayApi | AwsIotApi, str], Awaitable[None]]


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

_AIRJET_SPA_BUBBLES_SWITCH = BestwaySwitchEntityDescription(
    key="spa_wave_power",
    name="Spa Bubbles",
    icon=Icon.BUBBLES,
    value_fn=lambda s: bool(s.attrs["wave_power"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_bubbles(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_bubbles(device_id, False),
)

_AIRJET_SPA_LOCK_SWITCH = BestwaySwitchEntityDescription(
    key="spa_locked",
    name="Spa Locked",
    icon=Icon.LOCK,
    value_fn=lambda s: bool(s.attrs["locked"]),
    turn_on_fn=lambda api, device_id: api.airjet_spa_set_locked(device_id, True),
    turn_off_fn=lambda api, device_id: api.airjet_spa_set_locked(device_id, False),
)

_AIRJET_V01_HYDROJET_SPA_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_power",
    name="Spa Power",
    icon=Icon.POWER,
    value_fn=lambda s: bool(s.attrs["power"]),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_power(device_id, False),
)

_AIRJET_V01_HYDROJET_SPA_FILTER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_filter_power",
    name="Spa Filter",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.attrs["filter"] == 2),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_filter(
        device_id, HydrojetFilter.ON
    ),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_filter(
        device_id, HydrojetFilter.OFF
    ),
)

_HYDROJET_SPA_JETS_SWITCH = BestwaySwitchEntityDescription(
    key="spa_jets",
    name="Spa Jets",
    icon=Icon.JETS,
    value_fn=lambda s: bool(s.attrs["jet"]),
    turn_on_fn=lambda api, device_id: api.hydrojet_spa_set_jets(device_id, True),
    turn_off_fn=lambda api, device_id: api.hydrojet_spa_set_jets(device_id, False),
)

_POOL_FILTER_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="pool_filter_power",
    name="Pool Filter Power",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.attrs["power"]),
    turn_on_fn=lambda api, device_id: api.pool_filter_set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.pool_filter_set_power(device_id, False),
)


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
                    BestwaySwitch(
                        coordinator, config_entry, device_id, _AIRJET_SPA_POWER_SWITCH
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_SPA_FILTER_SWITCH,
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_SPA_BUBBLES_SWITCH,
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_SPA_LOCK_SWITCH,
                    ),
                ]
            )

        # V01 and V02 Airjet devices (normalization provides consistent field names)
        if device.device_type in [
            BestwayDeviceType.AIRJET_V01_SPA,
            BestwayDeviceType.AIRJET_V02,
            BestwayDeviceType.ULTRAFIT_AIRJET_V02,
        ]:
            entities.extend(
                [
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_V01_HYDROJET_SPA_POWER_SWITCH,
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_V01_HYDROJET_SPA_FILTER_SWITCH,
                    ),
                ]
            )

        # V01 and V02 Hydrojet devices (normalization provides consistent field names)
        if device.device_type in [
            BestwayDeviceType.HYDROJET_SPA,
            BestwayDeviceType.HYDROJET_PRO_SPA,
            BestwayDeviceType.HYDROJET_V02,
            BestwayDeviceType.HYDROJET_PRO_V02,
        ]:
            entities.extend(
                [
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_V01_HYDROJET_SPA_POWER_SWITCH,
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _AIRJET_V01_HYDROJET_SPA_FILTER_SWITCH,
                    ),
                    BestwaySwitch(
                        coordinator,
                        config_entry,
                        device_id,
                        _HYDROJET_SPA_JETS_SWITCH,
                    ),
                ]
            )

        if device.device_type == BestwayDeviceType.POOL_FILTER:
            entities.extend(
                [
                    BestwaySwitch(
                        coordinator, config_entry, device_id, _POOL_FILTER_POWER_SWITCH
                    )
                ]
            )

    async_add_entities(entities)


class BestwaySwitch(BestwayEntity, SwitchEntity):
    """Bestway switch entity."""

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

    _attr_assumed_state = True

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if status := self.status:
            return self.entity_description.value_fn(status)

        return None

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
        self._optimistic_state: bool | None = None

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state when real data arrives."""
        self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._optimistic_state = True
        self.async_write_ha_state()
        await self.entity_description.turn_on_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._optimistic_state = False
        self.async_write_ha_state()
        await self.entity_description.turn_off_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_request_refresh()
