"""Climate platform support."""

from __future__ import annotations

from time import monotonic
from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .const import DOMAIN
from .entity import BestwayEntity
from .features import features_for
from .model import HeaterState, TemperatureUnit

_OPTIMISTIC_TIMEOUT_S = 8.0

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
        features = features_for(device, config_entry.options)
        if features.climate:
            entities.append(SpaThermostat(coordinator, config_entry, device_id))

    async_add_entities(entities)


class SpaThermostat(BestwayEntity, ClimateEntity):
    """A thermostat that works for every spa device type.

    Reads/writes exclusively through DeviceStatus.heater and
    BackendApi.set_heat/set_target_temperature - no device-family branching
    needed, since the backend already normalized the heater state and wire
    encoding away.
    """

    _attr_name = "Spa Thermostat"
    _attr_supported_features = _CLIMATE_FEATURES
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]  # noqa: RUF012
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
        self._optimistic_heat: bool | None = None
        self._optimistic_heat_set_at: float = 0.0
        self._optimistic_tset: int | None = None
        self._optimistic_tset_set_at: float = 0.0

    def _set_optimistic_heat(self, value: bool) -> None:
        self._optimistic_heat = value
        self._optimistic_heat_set_at = monotonic()

    def _set_optimistic_tset(self, value: int) -> None:
        self._optimistic_tset = value
        self._optimistic_tset_set_at = monotonic()

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state once real data confirms it, or after a
        short timeout.

        Without the confirmation check, a refresh that fires before the
        cloud has acked the command exposes the stale state. Without the
        timeout, rapid input (or a dropped/reordered command) leaves the
        UI stuck on a value the cloud never reaches.
        """
        now = monotonic()
        if self.status is not None:
            if self._optimistic_heat is not None:
                actual_on = self.status.heater not in (None, HeaterState.OFF)
                timed_out = now - self._optimistic_heat_set_at >= _OPTIMISTIC_TIMEOUT_S
                if self._optimistic_heat == actual_on or timed_out:
                    self._optimistic_heat = None
            if self._optimistic_tset is not None:
                timed_out = now - self._optimistic_tset_set_at >= _OPTIMISTIC_TIMEOUT_S
                actual_tset = self.status.target_temperature
                matched = (
                    actual_tset is not None
                    and int(actual_tset) == self._optimistic_tset
                )
                if matched or timed_out:
                    self._optimistic_tset = None
        super()._handle_coordinator_update()

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current mode (HEAT or OFF)."""
        if self._optimistic_heat is not None:
            return HVACMode.HEAT if self._optimistic_heat else HVACMode.OFF
        if not self.status or self.status.heater is None:
            return None
        return HVACMode.OFF if self.status.heater is HeaterState.OFF else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running action (HEATING or IDLE)."""
        if self._optimistic_heat is not None:
            return HVACAction.HEATING if self._optimistic_heat else HVACAction.IDLE
        if not self.status or self.status.heater is None:
            return None
        return (
            HVACAction.HEATING
            if self.status.heater is HeaterState.HEATING
            else HVACAction.IDLE
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.status.current_temperature if self.status else None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self._optimistic_tset is not None:
            return float(self._optimistic_tset)
        return self.status.target_temperature if self.status else None

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if self.status and self.status.temperature_unit is TemperatureUnit.FAHRENHEIT:
            return str(UnitOfTemperature.FAHRENHEIT)
        return str(UnitOfTemperature.CELSIUS)

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
        self._set_optimistic_heat(want_heat)
        self.async_write_ha_state()
        await self.coordinator.api.set_heat(self.device_id, want_heat)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        target_temperature = kwargs.get(ATTR_TEMPERATURE)
        if target_temperature is None:
            return

        if hvac_mode := kwargs.get(ATTR_HVAC_MODE):
            want_heat = hvac_mode == HVACMode.HEAT
            self._set_optimistic_heat(want_heat)
            await self.coordinator.api.set_heat(self.device_id, want_heat)

        self._set_optimistic_tset(int(target_temperature))
        self.async_write_ha_state()
        await self.coordinator.api.set_target_temperature(
            self.device_id, target_temperature
        )
        await self.coordinator.async_request_refresh()
