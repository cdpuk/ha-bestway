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

        # V02 AWS IoT devices (use same entities - normalization handles field names)
        if device.device_type in [
            BestwayDeviceType.AIRJET_V02,
            BestwayDeviceType.ULTRAFIT_AIRJET_V02,
            BestwayDeviceType.HYDROJET_V02,
            BestwayDeviceType.HYDROJET_PRO_V02,
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
        await self.coordinator.async_request_refresh()

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
        await self.coordinator.async_request_refresh()


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
        self._optimistic_heat: int | None = None
        self._optimistic_tset: int | None = None

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state only once real data confirms the value.

        A refresh that fires before the cloud has acked the command would
        otherwise expose the stale state and flicker the UI back to the
        previous mode/temperature for a few hundred ms.
        """
        if self.status is not None:
            attrs = self.status.attrs
            if self._optimistic_heat is not None:
                want_on = self._optimistic_heat > 0
                actual_on = attrs.get("heat", 0) > 0
                if want_on == actual_on:
                    self._optimistic_heat = None
            if self._optimistic_tset is not None:
                try:
                    if int(attrs.get("Tset", -1)) == self._optimistic_tset:
                        self._optimistic_tset = None
                except (TypeError, ValueError):
                    pass
        super()._handle_coordinator_update()

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current mode (HEAT or OFF)."""
        if self._optimistic_heat is not None:
            return HVACMode.HEAT if self._optimistic_heat > 0 else HVACMode.OFF
        if not self.status:
            return None
        return HVACMode.HEAT if self.status.attrs["heat"] > 0 else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running action (HEATING or IDLE)."""
        heat_value: int | None = self._optimistic_heat
        if heat_value is None:
            if not self.status:
                return None
            heat_value = self.status.attrs["heat"]
        heat_on = heat_value > 0
        target_reached = heat_value == 4
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
        if self._optimistic_tset is not None:
            return float(self._optimistic_tset)
        if not self.status:
            return None
        return int(self.status.attrs["Tset"])

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if not self.status or self.status.attrs.get("Tunit", 1):
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
        want_heat = hvac_mode == HVACMode.HEAT
        self._optimistic_heat = int(HydrojetHeat.ON) if want_heat else int(
            HydrojetHeat.OFF
        )
        self.async_write_ha_state()
        await self.coordinator.api.hydrojet_spa_set_heat(
            self.device_id,
            HydrojetHeat.ON if want_heat else HydrojetHeat.OFF,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            want_heat = hvac_mode == HVACMode.HEAT
            self._optimistic_heat = int(HydrojetHeat.ON) if want_heat else int(
                HydrojetHeat.OFF
            )
            await self.coordinator.api.hydrojet_spa_set_heat(
                self.device_id,
                HydrojetHeat.ON if want_heat else HydrojetHeat.OFF,
            )

        self._optimistic_tset = int(target_temperature)
        self.async_write_ha_state()
        await self.coordinator.api.hydrojet_spa_set_target_temp(
            self.device_id, target_temperature
        )
        await self.coordinator.async_request_refresh()
