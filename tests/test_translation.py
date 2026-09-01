"""Table-driven tests for wire attrs -> typed DeviceStatus translation."""

from __future__ import annotations

import pytest

from custom_components.bestway.bestway.translation import status_from_attrs
from custom_components.bestway.model import (
    BestwayDeviceType,
    BubblesLevel,
    HeaterState,
    TemperatureUnit,
)

# ---------------------------------------------------------------------------
# Raw Airjet vocabulary (AIRJET_SPA only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({}, None),
        ({"heat_power": 0}, HeaterState.OFF),
        ({"heat_power": 1, "heat_temp_reach": 1}, HeaterState.TARGET_REACHED),
        ({"heat_power": 1, "heat_temp_reach": 0}, HeaterState.HEATING),
        ({"heat_power": 1}, HeaterState.HEATING),
    ],
)
def test_raw_airjet_heater_states(attrs: dict, expected: HeaterState | None) -> None:
    status = status_from_attrs(BestwayDeviceType.AIRJET_SPA, 1000, attrs)
    assert status.heater is expected


@pytest.mark.parametrize(
    ("temp_set_unit", "expected"),
    [
        ("摄氏", TemperatureUnit.CELSIUS),
        ("华氏", TemperatureUnit.FAHRENHEIT),
        (None, None),
    ],
)
def test_raw_airjet_temperature_unit(
    temp_set_unit: str | None, expected: TemperatureUnit | None
) -> None:
    attrs = {} if temp_set_unit is None else {"temp_set_unit": temp_set_unit}
    status = status_from_attrs(BestwayDeviceType.AIRJET_SPA, 1000, attrs)
    assert status.temperature_unit is expected


def test_raw_airjet_bubbles_binary() -> None:
    on = status_from_attrs(BestwayDeviceType.AIRJET_SPA, 1000, {"wave_power": 1})
    off = status_from_attrs(BestwayDeviceType.AIRJET_SPA, 1000, {"wave_power": 0})
    absent = status_from_attrs(BestwayDeviceType.AIRJET_SPA, 1000, {})
    assert on.bubbles is BubblesLevel.MAX
    assert off.bubbles is BubblesLevel.OFF
    assert absent.bubbles is None


def test_raw_airjet_basic_fields() -> None:
    status = status_from_attrs(
        BestwayDeviceType.AIRJET_SPA,
        1000,
        {
            "power": 1,
            "filter_power": 0,
            "locked": 1,
            "temp_now": 30,
            "temp_set": 38,
        },
    )
    assert status.power is True
    assert status.filtering is False
    assert status.locked is True
    assert status.current_temperature == 30
    assert status.target_temperature == 38


def test_raw_airjet_errors() -> None:
    status = status_from_attrs(
        BestwayDeviceType.AIRJET_SPA,
        1000,
        {"system_err1": 1, "system_err2": 0, "earth": 1, "power": 1},
    )
    assert status.errors == ["earth", "system_err1"]


# ---------------------------------------------------------------------------
# V01 vocabulary (everything else spa - native V01 and AWS/SmartSpa-normalized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heat", "expected"),
    [
        (None, None),
        (0, HeaterState.OFF),
        (1, HeaterState.HEATING),
        (2, HeaterState.HEATING),
        (3, HeaterState.HEATING),
        (4, HeaterState.TARGET_REACHED),
    ],
)
def test_v01_heater_states(heat: int | None, expected: HeaterState | None) -> None:
    attrs = {} if heat is None else {"heat": heat}
    status = status_from_attrs(BestwayDeviceType.AIRJET_V01_SPA, 1000, attrs)
    assert status.heater is expected


@pytest.mark.parametrize(
    ("tunit", "expected"),
    [
        (None, None),
        (0, TemperatureUnit.FAHRENHEIT),
        (1, TemperatureUnit.CELSIUS),
    ],
)
def test_v01_temperature_unit(
    tunit: int | None, expected: TemperatureUnit | None
) -> None:
    attrs = {} if tunit is None else {"Tunit": tunit}
    status = status_from_attrs(BestwayDeviceType.AIRJET_V01_SPA, 1000, attrs)
    assert status.temperature_unit is expected


@pytest.mark.parametrize(
    ("device_type", "wave", "expected"),
    [
        # Airjet-style map: MEDIUM read as 40/41/50/51
        (BestwayDeviceType.AIRJET_V01_SPA, 0, BubblesLevel.OFF),
        (BestwayDeviceType.AIRJET_V01_SPA, 40, BubblesLevel.MEDIUM),
        (BestwayDeviceType.AIRJET_V01_SPA, 50, BubblesLevel.MEDIUM),
        (BestwayDeviceType.AIRJET_V01_SPA, 51, BubblesLevel.MEDIUM),
        (BestwayDeviceType.AIRJET_V01_SPA, 100, BubblesLevel.MAX),
        (BestwayDeviceType.AIRJET_V02, 41, BubblesLevel.MEDIUM),
        # Hydrojet-style map: MEDIUM read as 40-43
        (BestwayDeviceType.HYDROJET_SPA, 42, BubblesLevel.MEDIUM),
        (BestwayDeviceType.HYDROJET_PRO_V02, 43, BubblesLevel.MEDIUM),
        (BestwayDeviceType.HYDROJET_SPA, 100, BubblesLevel.MAX),
        (BestwayDeviceType.HYDROJET_SPA, 0, BubblesLevel.OFF),
        # Unrecognised value falls back to OFF rather than raising
        (BestwayDeviceType.AIRJET_V01_SPA, 99, BubblesLevel.OFF),
    ],
)
def test_v01_bubbles_read_map_by_device_type(
    device_type: BestwayDeviceType, wave: int, expected: BubblesLevel
) -> None:
    status = status_from_attrs(device_type, 1000, {"wave": wave})
    assert status.bubbles is expected


def test_v01_bubbles_absent_is_none() -> None:
    status = status_from_attrs(BestwayDeviceType.AIRJET_V01_SPA, 1000, {})
    assert status.bubbles is None


def test_v01_basic_fields() -> None:
    status = status_from_attrs(
        BestwayDeviceType.HYDROJET_SPA,
        1000,
        {
            "power": True,
            "filter": 2,
            "jet": True,
            "locked": False,
            "Tnow": 30,
            "Tset": 39,
            "wifi_version": "1.2.3",
            "trd_version": "4.5.6",
            "ota_status": "idle",
        },
    )
    assert status.power is True
    assert status.filtering is True  # wire value 2 ("ON") is still truthy
    assert status.jets is True
    assert status.locked is False
    assert status.current_temperature == 30
    assert status.target_temperature == 39
    assert status.wifi_version == "1.2.3"
    assert status.trd_version == "4.5.6"
    assert status.ota_status == "idle"


def test_v01_errors_exclude_e32_and_include_error_code() -> None:
    status = status_from_attrs(
        BestwayDeviceType.AIRJET_V01_SPA,
        1000,
        {"E02": 1, "E32": 1, "E10": 0, "error": 1},
    )
    assert status.errors == ["E02", "error"]


def test_v01_no_errors_when_nothing_set() -> None:
    status = status_from_attrs(BestwayDeviceType.AIRJET_V01_SPA, 1000, {})
    assert status.errors == []


# ---------------------------------------------------------------------------
# Pool filter vocabulary
# ---------------------------------------------------------------------------


def test_pool_filter_fields() -> None:
    status = status_from_attrs(
        BestwayDeviceType.POOL_FILTER,
        1000,
        {"power": True, "time": 6, "filter": 1, "error": 0},
    )
    assert status.power is True
    assert status.filter_timer_hours == 6
    assert status.filter_change_required is True
    assert status.errors == []


def test_pool_filter_error() -> None:
    status = status_from_attrs(
        BestwayDeviceType.POOL_FILTER, 1000, {"error": 1, "power": False}
    )
    assert status.errors == ["error"]
    assert status.power is False


def test_pool_filter_absent_timer_is_none() -> None:
    status = status_from_attrs(BestwayDeviceType.POOL_FILTER, 1000, {})
    assert status.filter_timer_hours is None
    assert status.filter_change_required is None


# ---------------------------------------------------------------------------
# UNKNOWN and sparse deltas
# ---------------------------------------------------------------------------


def test_unknown_device_type_only_carries_timestamp_and_attrs() -> None:
    status = status_from_attrs(BestwayDeviceType.UNKNOWN, 1000, {"power": 1})
    assert status.timestamp == 1000
    assert status.attrs == {"power": 1}
    assert status.power is None
    assert status.heater is None
    assert status.errors == []


def test_sparse_websocket_delta_leaves_untouched_fields_none() -> None:
    """A delta carrying only one changed field must not fabricate the rest."""
    status = status_from_attrs(BestwayDeviceType.HYDROJET_SPA, 1000, {"Tnow": 31})
    assert status.current_temperature == 31
    assert status.power is None
    assert status.filtering is None
    assert status.heater is None
    assert status.bubbles is None
    assert status.jets is None
    assert status.locked is None
    assert status.errors == []


def test_malformed_wave_value_does_not_crash_translation() -> None:
    """A stale cache entry (see the Gizwits BubblesValues cache bug) must not
    crash translation; it should surface as unknown bubbles instead.
    """

    class _NotAnInt:
        pass

    status = status_from_attrs(
        BestwayDeviceType.HYDROJET_SPA, 1000, {"wave": _NotAnInt()}
    )
    assert status.bubbles is None
