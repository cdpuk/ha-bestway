"""Entity -> semantic setter wiring tests.

Verifies that each entity action (switch on/off, select option, number set,
climate hvac_mode/set_temperature) calls exactly one BackendApi semantic
setter with the expected arguments. Nothing previously asserted this - the
existing switch/select tests only ever checked optimistic UI state, never
which API method actually fired.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate.const import ATTR_HVAC_MODE, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.bestway.climate import SpaThermostat
from custom_components.bestway.model import (
    BestwayApiResults,
    BestwayDevice,
    BubblesLevel,
    DeviceStatus,
)
from custom_components.bestway.number import _POOL_FILTER_TIME, PoolFilterTimeNumber
from custom_components.bestway.select import ThreeWaySpaBubblesSelect
from custom_components.bestway.switch import (
    _SPA_BUBBLES_SWITCH,
    _SPA_FILTER_SWITCH,
    _SPA_JETS_SWITCH,
    _SPA_LOCK_SWITCH,
    _SPA_POWER_SWITCH,
    BestwaySwitch,
)

pytestmark = pytest.mark.asyncio


def _make_device() -> BestwayDevice:
    return BestwayDevice(
        protocol_version=2,
        device_id="test_device",
        product_name="AIRJET",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
    )


def _make_status() -> DeviceStatus:
    return DeviceStatus(timestamp=1000)


def _make_coordinator(device: BestwayDevice, status: DeviceStatus) -> MagicMock:
    """A coordinator whose api exposes every semantic setter as an AsyncMock."""
    coordinator = MagicMock()
    coordinator.api = MagicMock()
    coordinator.api.devices = {"test_device": device}
    for method in (
        "set_power",
        "set_filter",
        "set_heat",
        "set_locked",
        "set_jets",
        "set_bubbles",
        "set_target_temperature",
        "set_pool_timer",
    ):
        setattr(coordinator.api, method, AsyncMock())
    coordinator.data = BestwayApiResults(devices={"test_device": status})
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _without_ha_state_writes(entity):
    """Entities call async_write_ha_state() for optimistic UI updates, which
    requires a real hass instance we don't have in these unit tests. Stub it
    out - these tests only care which setter was called, not entity state.
    """
    entity.async_write_ha_state = MagicMock()
    return entity


# ---------------------------------------------------------------------------
# switch.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "setter_name"),
    [
        (_SPA_POWER_SWITCH, "set_power"),
        (_SPA_FILTER_SWITCH, "set_filter"),
        (_SPA_LOCK_SWITCH, "set_locked"),
        (_SPA_JETS_SWITCH, "set_jets"),
    ],
)
async def test_switch_turn_on_calls_expected_setter(description, setter_name):
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    switch = _without_ha_state_writes(
        BestwaySwitch(coordinator, config_entry, "test_device", description)
    )

    await switch.async_turn_on()

    getattr(coordinator.api, setter_name).assert_awaited_once_with("test_device", True)


@pytest.mark.parametrize(
    ("description", "setter_name"),
    [
        (_SPA_POWER_SWITCH, "set_power"),
        (_SPA_FILTER_SWITCH, "set_filter"),
        (_SPA_LOCK_SWITCH, "set_locked"),
        (_SPA_JETS_SWITCH, "set_jets"),
    ],
)
async def test_switch_turn_off_calls_expected_setter(description, setter_name):
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    switch = _without_ha_state_writes(
        BestwaySwitch(coordinator, config_entry, "test_device", description)
    )

    await switch.async_turn_off()

    getattr(coordinator.api, setter_name).assert_awaited_once_with("test_device", False)


async def test_bubbles_switch_on_off_calls_set_bubbles():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    switch = _without_ha_state_writes(
        BestwaySwitch(coordinator, config_entry, "test_device", _SPA_BUBBLES_SWITCH)
    )

    await switch.async_turn_on()
    coordinator.api.set_bubbles.assert_awaited_once_with(
        "test_device", BubblesLevel.MAX
    )

    coordinator.api.set_bubbles.reset_mock()
    await switch.async_turn_off()
    coordinator.api.set_bubbles.assert_awaited_once_with(
        "test_device", BubblesLevel.OFF
    )


# ---------------------------------------------------------------------------
# select.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("option", "level"),
    [
        ("OFF", BubblesLevel.OFF),
        ("MEDIUM", BubblesLevel.MEDIUM),
        ("MAX", BubblesLevel.MAX),
    ],
)
async def test_select_option_calls_set_bubbles(option, level):
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    select = ThreeWaySpaBubblesSelect(coordinator, config_entry, "test_device")

    await select.async_select_option(option)

    coordinator.api.set_bubbles.assert_awaited_once_with("test_device", level)


# ---------------------------------------------------------------------------
# number.py
# ---------------------------------------------------------------------------


async def test_pool_filter_number_calls_set_pool_timer():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    number = PoolFilterTimeNumber(
        coordinator, config_entry, "test_device", _POOL_FILTER_TIME
    )

    await number.async_set_native_value(6.0)

    coordinator.api.set_pool_timer.assert_awaited_once_with("test_device", 6)


# ---------------------------------------------------------------------------
# climate.py
# ---------------------------------------------------------------------------


async def test_climate_set_hvac_mode_heat_calls_set_heat_true():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    thermostat = _without_ha_state_writes(
        SpaThermostat(coordinator, config_entry, "test_device")
    )

    await thermostat.async_set_hvac_mode(HVACMode.HEAT)

    coordinator.api.set_heat.assert_awaited_once_with("test_device", True)


async def test_climate_set_hvac_mode_off_calls_set_heat_false():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    thermostat = _without_ha_state_writes(
        SpaThermostat(coordinator, config_entry, "test_device")
    )

    await thermostat.async_set_hvac_mode(HVACMode.OFF)

    coordinator.api.set_heat.assert_awaited_once_with("test_device", False)


async def test_climate_set_temperature_calls_set_target_temperature():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    thermostat = _without_ha_state_writes(
        SpaThermostat(coordinator, config_entry, "test_device")
    )

    await thermostat.async_set_temperature(**{ATTR_TEMPERATURE: 38})

    coordinator.api.set_target_temperature.assert_awaited_once_with("test_device", 38)
    coordinator.api.set_heat.assert_not_awaited()


async def test_climate_set_temperature_with_hvac_mode_also_calls_set_heat():
    coordinator = _make_coordinator(_make_device(), _make_status())
    config_entry = MagicMock()
    thermostat = _without_ha_state_writes(
        SpaThermostat(coordinator, config_entry, "test_device")
    )

    await thermostat.async_set_temperature(
        **{ATTR_TEMPERATURE: 38, ATTR_HVAC_MODE: HVACMode.HEAT}
    )

    coordinator.api.set_heat.assert_awaited_once_with("test_device", True)
    coordinator.api.set_target_temperature.assert_awaited_once_with("test_device", 38)


async def test_climate_optimistic_heat_renders_immediately_for_every_device_type():
    """Every device type (including former raw-Airjet devices, which had no
    optimistic path before the thermostats were unified) shows HEAT/HEATING
    immediately after async_set_hvac_mode, before any coordinator refresh
    confirms it.
    """
    status = _make_status()  # heater stays None: cloud hasn't confirmed yet
    coordinator = _make_coordinator(_make_device(), status)
    config_entry = MagicMock()
    thermostat = _without_ha_state_writes(
        SpaThermostat(coordinator, config_entry, "test_device")
    )

    await thermostat.async_set_hvac_mode(HVACMode.HEAT)

    assert thermostat.hvac_mode == HVACMode.HEAT
    assert thermostat.hvac_action == HVACAction.HEATING
