"""Climate platform support."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    PRECISION_WHOLE,
    TEMP_CELSIUS,
    TEMP_FAHRENHEIT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .bestway.model import TemperatureUnit
from .const import DOMAIN
from .entity import BestwayEntity, BestwaySpaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BestwayEntity] = []
    entities.extend(
        SpaThermostat(coordinator, config_entry, device_id)
        for device_id in coordinator.data.spa_devices.keys()
    )
    async_add_entities(entities)


class SpaThermostat(BestwaySpaEntity, ClimateEntity):
    """The main thermostat entity for a spa."""

    _attr_name = "Spa Thermostat"
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize thermostat."""
        super().__init__(coordinator, config_entry, device_id)
        self._attr_unique_id = f"{device_id}_thermostat"

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        """Return the current mode (HEAT or OFF)."""
        if not self.status:
            return None
        return HVACMode.HEAT if self.status.heat_power else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | str | None:
        """Return the current running action (HEATING or IDLE)."""
        if not self.status:
            return None
        heat_on = self.status.heat_power
        target_reached = self.status.heat_temp_reach
        return (
            HVACAction.HEATING if (heat_on and not target_reached) else HVACAction.IDLE
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if not self.status:
            return None
        return self.status.temp_now

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if not self.status:
            return None
        return self.status.temp_set

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if not self.status or self.status.temp_set_unit == TemperatureUnit.CELSIUS:
            return str(TEMP_CELSIUS)
        else:
            return str(TEMP_FAHRENHEIT)

    @property
    def min_temp(self) -> float:
        """
        Get the minimum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return 20 if self.temperature_unit == TEMP_CELSIUS else 68

    @property
    def max_temp(self) -> float:
        """
        Get the maximum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return 40 if self.temperature_unit == TEMP_CELSIUS else 104

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        should_heat = hvac_mode == HVACMode.HEAT
        await self.coordinator.api.spa_set_heat(self.device_id, should_heat)
        await self.coordinator.async_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            should_heat = hvac_mode == HVACMode.HEAT
            await self.coordinator.api.spa_set_heat(self.device_id, should_heat)

        await self.coordinator.api.spa_set_target_temp(
            self.device_id, target_temperature
        )
        await self.coordinator.async_refresh()
