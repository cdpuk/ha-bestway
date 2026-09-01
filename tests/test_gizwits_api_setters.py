"""Tests for the Gizwits backend's semantic setters.

Covers, per BestwayDeviceType vocabulary (raw Airjet / V01-normalized /
pool filter): the exact POST body sent, the optimistic raw-cache cascade
applied, and which setter/device combinations correctly raise
NotImplementedError instead of silently no-opping.

Also regression-tests the two bugs fixed when these setters were unified:
  1. Airjet power/filter/heat/bubbles used to cache under the dead key
     "spa_power" while readers read "power".
  2. Hydrojet power-off/filter-off used to cache "wave" as a BubblesValues
     *object* (HYDROJET_BUBBLES_MAP.off_val) instead of the int 0.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bestway.bestway.api import BestwayApi, BestwayException
from custom_components.bestway.bestway.model import HydrojetFilter, HydrojetHeat
from custom_components.bestway.model import (
    BestwayDevice,
    BestwayDeviceType,
    BubblesLevel,
    RawSnapshot,
)

_PRODUCT_NAME = {
    BestwayDeviceType.AIRJET_SPA: "Airjet",
    BestwayDeviceType.AIRJET_V01_SPA: "Airjet_V01",
    BestwayDeviceType.HYDROJET_SPA: "Hydrojet",
    BestwayDeviceType.POOL_FILTER: "泳池过滤器",
}


def _ok_response(json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.ok = True
    response.json = AsyncMock(return_value=json_data or {})
    return response


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.post = AsyncMock(return_value=_ok_response())
    return session


@pytest.fixture
def api(mock_session):
    return BestwayApi(mock_session, "token", "https://example.invalid")


def _seed(api: BestwayApi, device_id: str, device_type: BestwayDeviceType) -> None:
    """Register a device and give it an empty polled cache entry."""
    api.devices[device_id] = BestwayDevice(
        protocol_version=1,
        device_id=device_id,
        product_name=_PRODUCT_NAME[device_type],
        alias="Test",
        mcu_soft_version="1",
        mcu_hard_version="1",
        wifi_soft_version="1",
        wifi_hard_version="1",
        is_online=True,
    )
    api._raw_state[device_id] = RawSnapshot(1000, {})


def _posted_attrs(mock_session) -> dict:
    """The 'attrs' body of the most recent control POST."""
    _, kwargs = mock_session.post.call_args
    return dict(kwargs["json"]["attrs"])


# ---------------------------------------------------------------------------
# set_power
# ---------------------------------------------------------------------------


async def test_set_power_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_power("d", True)
    assert _posted_attrs(mock_session) == {"power": 1}
    assert api._raw_state["d"].attrs["power"] == 1  # regression: not "spa_power"


async def test_set_power_off_cascades_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_power("d", False)
    assert _posted_attrs(mock_session) == {"power": 0}
    attrs = api._raw_state["d"].attrs
    assert attrs["power"] == 0
    assert attrs["filter_power"] == 0
    assert attrs["heat_power"] == 0
    assert attrs["wave_power"] == 0


async def test_set_power_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_power("d", True)
    assert _posted_attrs(mock_session) == {"power": 1}
    assert api._raw_state["d"].attrs["power"] is True


async def test_set_power_off_cascades_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_power("d", False)
    attrs = api._raw_state["d"].attrs
    assert attrs["power"] is False
    assert attrs["filter"] == 0
    assert attrs["heat"] == 0
    assert attrs["wave"] == 0  # regression: plain int, not a BubblesValues object


async def test_set_power_on_pool_filter(api, mock_session):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    await api.set_power("d", True)
    assert _posted_attrs(mock_session) == {"power": 1}
    assert api._raw_state["d"].attrs["power"] is True


# ---------------------------------------------------------------------------
# set_filter
# ---------------------------------------------------------------------------


async def test_set_filter_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_filter("d", True)
    assert _posted_attrs(mock_session) == {"filter_power": 1}
    attrs = api._raw_state["d"].attrs
    assert attrs["filter_power"] == 1
    assert attrs["power"] == 1


async def test_set_filter_off_cascades_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_filter("d", False)
    attrs = api._raw_state["d"].attrs
    assert attrs["filter_power"] == 0
    assert attrs["wave_power"] == 0
    assert attrs["heat_power"] == 0


async def test_set_filter_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_filter("d", True)
    assert _posted_attrs(mock_session) == {"filter": HydrojetFilter.ON}
    attrs = api._raw_state["d"].attrs
    assert attrs["filter"] == HydrojetFilter.ON
    assert attrs["power"] == 1


async def test_set_filter_off_cascades_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_filter("d", False)
    assert _posted_attrs(mock_session) == {"filter": HydrojetFilter.OFF}
    attrs = api._raw_state["d"].attrs
    assert attrs["wave"] == 0  # regression: plain int, not a BubblesValues object
    assert attrs["heat"] == 0


async def test_set_filter_not_implemented_on_pool_filter(api):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    with pytest.raises(NotImplementedError):
        await api.set_filter("d", True)


# ---------------------------------------------------------------------------
# set_heat
# ---------------------------------------------------------------------------


async def test_set_heat_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_heat("d", True)
    assert _posted_attrs(mock_session) == {"heat_power": 1}
    attrs = api._raw_state["d"].attrs
    assert attrs["heat_power"] == 1
    assert attrs["power"] == 1
    assert attrs["filter_power"] == 1


async def test_set_heat_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_heat("d", True)
    assert _posted_attrs(mock_session) == {"heat": HydrojetHeat.ON}
    attrs = api._raw_state["d"].attrs
    assert attrs["heat"] == HydrojetHeat.ON
    assert attrs["power"] == 1
    assert attrs["filter"] == HydrojetFilter.ON


async def test_set_heat_not_implemented_on_pool_filter(api):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    with pytest.raises(NotImplementedError):
        await api.set_heat("d", True)


# ---------------------------------------------------------------------------
# set_target_temperature
# ---------------------------------------------------------------------------


async def test_set_target_temperature_on_raw_airjet(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_target_temperature("d", 38)
    assert _posted_attrs(mock_session) == {"temp_set": 38}
    assert api._raw_state["d"].attrs["temp_set"] == 38


async def test_set_target_temperature_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_target_temperature("d", 38)
    assert _posted_attrs(mock_session) == {"Tset": 38}
    assert api._raw_state["d"].attrs["Tset"] == 38


async def test_set_target_temperature_not_implemented_on_pool_filter(api):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    with pytest.raises(NotImplementedError):
        await api.set_target_temperature("d", 38)


# ---------------------------------------------------------------------------
# set_locked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "device_type", [BestwayDeviceType.AIRJET_SPA, BestwayDeviceType.AIRJET_V01_SPA]
)
async def test_set_locked_same_field_for_raw_and_v01(api, mock_session, device_type):
    _seed(api, "d", device_type)
    await api.set_locked("d", True)
    assert _posted_attrs(mock_session) == {"locked": 1}
    assert api._raw_state["d"].attrs["locked"] == 1


async def test_set_locked_not_implemented_on_pool_filter(api):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    with pytest.raises(NotImplementedError):
        await api.set_locked("d", True)


# ---------------------------------------------------------------------------
# set_jets
# ---------------------------------------------------------------------------


async def test_set_jets_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.HYDROJET_SPA)
    await api.set_jets("d", True)
    assert _posted_attrs(mock_session) == {"jet": 1}
    attrs = api._raw_state["d"].attrs
    assert attrs["jet"] == 1
    assert attrs["power"] == 1


@pytest.mark.parametrize(
    "device_type", [BestwayDeviceType.AIRJET_SPA, BestwayDeviceType.POOL_FILTER]
)
async def test_set_jets_not_implemented(api, device_type):
    _seed(api, "d", device_type)
    with pytest.raises(NotImplementedError):
        await api.set_jets("d", True)


# ---------------------------------------------------------------------------
# set_bubbles
# ---------------------------------------------------------------------------


async def test_set_bubbles_raw_airjet_off(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_bubbles("d", BubblesLevel.OFF)
    assert _posted_attrs(mock_session) == {"wave_power": 0}
    attrs = api._raw_state["d"].attrs
    assert attrs["wave_power"] == 0
    assert "power" not in attrs


@pytest.mark.parametrize("level", [BubblesLevel.MEDIUM, BubblesLevel.MAX])
async def test_set_bubbles_raw_airjet_treats_medium_as_on(
    api, mock_session, level: BubblesLevel
):
    """Raw Airjet bubbles hardware is binary: MEDIUM and MAX both mean on."""
    _seed(api, "d", BestwayDeviceType.AIRJET_SPA)
    await api.set_bubbles("d", level)
    assert _posted_attrs(mock_session) == {"wave_power": 1}
    attrs = api._raw_state["d"].attrs
    assert attrs["wave_power"] == 1
    assert attrs["power"] == 1


@pytest.mark.parametrize(
    ("level", "expected_wire_value"),
    [(BubblesLevel.OFF, 0), (BubblesLevel.MEDIUM, 50), (BubblesLevel.MAX, 100)],
)
async def test_set_bubbles_airjet_v01_uses_airjet_map(
    api, mock_session, level: BubblesLevel, expected_wire_value: int
):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_bubbles("d", level)
    assert _posted_attrs(mock_session) == {"wave": expected_wire_value}
    assert api._raw_state["d"].attrs["wave"] == expected_wire_value


@pytest.mark.parametrize(
    ("level", "expected_wire_value"),
    [(BubblesLevel.OFF, 0), (BubblesLevel.MEDIUM, 40), (BubblesLevel.MAX, 100)],
)
async def test_set_bubbles_hydrojet_uses_hydrojet_map(
    api, mock_session, level: BubblesLevel, expected_wire_value: int
):
    _seed(api, "d", BestwayDeviceType.HYDROJET_SPA)
    await api.set_bubbles("d", level)
    assert _posted_attrs(mock_session) == {"wave": expected_wire_value}
    assert api._raw_state["d"].attrs["wave"] == expected_wire_value


async def test_set_bubbles_non_off_cascades_power_on_v01(api, mock_session):
    _seed(api, "d", BestwayDeviceType.AIRJET_V01_SPA)
    await api.set_bubbles("d", BubblesLevel.MAX)
    assert api._raw_state["d"].attrs["power"] == 1


async def test_set_bubbles_not_implemented_on_pool_filter(api):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    with pytest.raises(NotImplementedError):
        await api.set_bubbles("d", BubblesLevel.MAX)


# ---------------------------------------------------------------------------
# set_pool_timer
# ---------------------------------------------------------------------------


async def test_set_pool_timer_on_pool_filter(api, mock_session):
    _seed(api, "d", BestwayDeviceType.POOL_FILTER)
    await api.set_pool_timer("d", 6)
    assert _posted_attrs(mock_session) == {"time": 6}
    assert api._raw_state["d"].attrs["time"] == 6


@pytest.mark.parametrize(
    "device_type", [BestwayDeviceType.AIRJET_SPA, BestwayDeviceType.AIRJET_V01_SPA]
)
async def test_set_pool_timer_not_implemented_on_spa(api, device_type):
    _seed(api, "d", device_type)
    with pytest.raises(NotImplementedError):
        await api.set_pool_timer("d", 6)


# ---------------------------------------------------------------------------
# Guard: unrecognised / unpolled devices
# ---------------------------------------------------------------------------


async def test_set_power_raises_for_unregistered_device(api):
    """A device with no entry in api.devices at all."""
    with pytest.raises(BestwayException):
        await api.set_power("nonexistent", True)


async def test_set_power_raises_for_registered_but_unpolled_device(api):
    """A device known via refresh_bindings() but never successfully polled -
    there's no cache entry to apply the optimistic cascade to.
    """
    api.devices["d"] = BestwayDevice(
        protocol_version=1,
        device_id="d",
        product_name="Airjet",
        alias="Test",
        mcu_soft_version="1",
        mcu_hard_version="1",
        wifi_soft_version="1",
        wifi_hard_version="1",
        is_online=True,
    )
    with pytest.raises(BestwayException):
        await api.set_power("d", True)
