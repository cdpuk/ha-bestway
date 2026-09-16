"""The device re-discovery policy shared by every backend.

`refresh_bindings()` runs on every coordinator poll (30 s, or 5 minutes while a
WebSocket is connected), while the device list only changes when a device is
added, removed or renamed in the Bestway app. `RawStateApi._bindings_are_stale()`
owns that throttle, so all three backends age the list out identically.
"""

from time import time

from custom_components.bestway.model import BestwayDevice
from custom_components.bestway.raw_state import (
    DEVICE_REDISCOVERY_INTERVAL_S,
    RawStateApi,
)


def _device() -> BestwayDevice:
    return BestwayDevice(
        protocol_version=1,
        device_id="device1",
        product_name="Airjet",
        alias="Test Spa",
        mcu_soft_version="1",
        mcu_hard_version="1",
        wifi_soft_version="1",
        wifi_hard_version="1",
        is_online=True,
    )


def test_empty_device_list_is_always_stale() -> None:
    """An empty list keeps retrying, so a failed or empty discovery is not
    cached for the next 15 minutes.
    """
    api = RawStateApi()
    assert api._bindings_are_stale()

    api._mark_bindings_refreshed()
    assert api._bindings_are_stale()


def test_fresh_device_list_is_reused() -> None:
    """A list that was just discovered is not fetched again."""
    api = RawStateApi()
    api.devices = {"device1": _device()}
    api._mark_bindings_refreshed()

    assert not api._bindings_are_stale()


def test_device_list_ages_out() -> None:
    """Once the interval has passed, the next poll re-discovers."""
    api = RawStateApi()
    api.devices = {"device1": _device()}
    api._mark_bindings_refreshed()

    api._bindings_refreshed_at = time() - DEVICE_REDISCOVERY_INTERVAL_S + 30
    assert not api._bindings_are_stale()

    api._bindings_refreshed_at = time() - DEVICE_REDISCOVERY_INTERVAL_S - 1
    assert api._bindings_are_stale()
