"""Climate platform support."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .bestway.model import BestwayDeviceType, HydrojetHeat
from .const import DOMAIN
from .entity import BestwayEntity

_SPA_MIN_TEMP_C = 20
_SPA_MIN_TEMP_F = 68
_SPA_MAX_TEMP_C = 40
_SPA_MAX_TEMP_F = 104
_CLIMATE_FEATURES = (
    ClimateEntityFeature.TARGET_TEMPERATURE
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.TURN_ON
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        if device.device_type == BestwayDeviceType.AIRJET_SPA:
            entities.append(AirjetSpaThermostat(coordinator, config_entry, device_id))

        if device.device_type in [
            BestwayDeviceType.AIRJET_V01_SPA,
            BestwayDeviceType.HYDROJET_SPA,
            BestwayDeviceType.HYDROJET_PRO_SPA,
        ]:
            entities.append(
                AirjetV01HydrojetSpaThermostat(coordinator, config_entry, device_id)
            )

    async_add_entities(entities)


class AirjetSpaThermostat(BestwayEntity, ClimateEntity):
    """A thermostat that works for Airjet spa devices."""

    _attr_name = "Spa Thermostat"
    _attr_supported_features = _CLIMATE_FEATURES
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1
    _enable_turn_on_off_backwards_compatibility = False

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
    def hvac_mode(self) -> HVACMode | None:
        """Return the current mode (HEAT or OFF)."""
        if not self.status:
            return None
        return HVACMode.HEAT if self.status.attrs["heat_power"] else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running action (HEATING or IDLE)."""
        if not self.status:
            return None
        heat_on = self.status.attrs["heat_power"]
        target_reached = self.status.attrs["heat_temp_reach"]
        return (
            HVACAction.HEATING if (heat_on and not target_reached) else HVACAction.IDLE
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if not self.status:
            return None
        return int(self.status.attrs["temp_now"])

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if not self.status:
            return None
        return int(self.status.attrs["temp_set"])

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if not self.status or self.status.attrs["temp_set_unit"] == "摄氏":
            return str(UnitOfTemperature.CELSIUS)
        else:
            return str(UnitOfTemperature.FAHRENHEIT)

    @property
    def min_temp(self) -> float:
        """
        Get the minimum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return (
            _SPA_MIN_TEMP_C
            if self.temperature_unit == UnitOfTemperature.CELSIUS
            else _SPA_MIN_TEMP_F
        )

    @property
    def max_temp(self) -> float:
        """
        Get the maximum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return (
            _SPA_MAX_TEMP_C
            if self.temperature_unit == UnitOfTemperature.CELSIUS
            else _SPA_MAX_TEMP_F
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        should_heat = hvac_mode == HVACMode.HEAT
        await self.coordinator.api.airjet_spa_set_heat(self.device_id, should_heat)
        await self.coordinator.async_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            should_heat = hvac_mode == HVACMode.HEAT
            await self.coordinator.api.airjet_spa_set_heat(self.device_id, should_heat)

        await self.coordinator.api.airjet_spa_set_target_temp(
            self.device_id, target_temperature
        )
        await self.coordinator.async_refresh()


class AirjetV01HydrojetSpaThermostat(BestwayEntity, ClimateEntity):
    """A thermostat that works for Airjet_V01 and Hydrojet devices."""

    _attr_name = "Spa Thermostat"
    _attr_supported_features = _CLIMATE_FEATURES
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1
    _enable_turn_on_off_backwards_compatibility = False

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
    def hvac_mode(self) -> HVACMode | None:
        """Return the current mode (HEAT or OFF)."""
        if not self.status:
            return None
        return HVACMode.HEAT if self.status.attrs["heat"] == 3 else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running action (HEATING or IDLE)."""
        if not self.status:
            return None
        heat_on = self.status.attrs["heat"] == HydrojetHeat.ON
        target_reached = self.status.attrs["word3"] == 1
        return (
            HVACAction.HEATING if (heat_on and not target_reached) else HVACAction.IDLE
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if not self.status:
            return None
        return int(self.status.attrs["Tnow"])

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if not self.status:
            return None
        return int(self.status.attrs["Tset"])

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if not self.status or self.status.attrs["Tunit"]:
            return str(UnitOfTemperature.CELSIUS)
        else:
            return str(UnitOfTemperature.FAHRENHEIT)

    @property
    def min_temp(self) -> float:
        """
        Get the minimum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return (
            _SPA_MIN_TEMP_C
            if self.temperature_unit == UnitOfTemperature.CELSIUS
            else _SPA_MIN_TEMP_F
        )

    @property
    def max_temp(self) -> float:
        """
        Get the maximum temperature that a user can set.

        As the Spa can be switched between temperature units, this needs to be dynamic.
        """
        return (
            _SPA_MAX_TEMP_C
            if self.temperature_unit == UnitOfTemperature.CELSIUS
            else _SPA_MAX_TEMP_F
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            await self.coordinator.api.hydrojet_spa_set_heat(
                self.device_id, HydrojetHeat.ON
            )
        else:
            await self.coordinator.api.hydrojet_spa_set_heat(
                self.device_id, HydrojetHeat.OFF
            )
        await self.coordinator.async_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            should_heat = hvac_mode == HVACMode.HEAT
            await self.coordinator.api.hydrojet_spa_set_heat(
                self.device_id, should_heat
            )

        await self.coordinator.api.hydrojet_spa_set_target_temp(
            self.device_id, target_temperature
        )
        await self.coordinator.async_refresh()
