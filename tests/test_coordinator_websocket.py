"""Integration tests for WebSocket coordinator callbacks."""

import asyncio
from datetime import timedelta
from time import time
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bestway.bestway.api import BestwayApi
from custom_components.bestway.const import (
    BACKEND_GIZWITS,
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    DOMAIN,
)
from custom_components.bestway.coordinator import BestwayUpdateCoordinator
from custom_components.bestway.model import BestwayDevice, BestwayDeviceType


def _make_api() -> BestwayApi:
    """A real BestwayApi so handle_websocket_update exercises the actual
    merge-and-translate path, not a mock standing in for it.
    """
    return BestwayApi(MagicMock(), "token", "https://example.invalid")


@pytest.mark.asyncio
async def test_coordinator_websocket_update(hass: HomeAssistant):
    """Test coordinator receives and processes WebSocket updates."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = _make_api()
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Simulate WebSocket update
    test_attrs = {
        "power": 1,
        "temp_now": 36,
        "temp_set": 38,
        "heat_power": 1,
    }

    coordinator.handle_websocket_update("device123", test_attrs)

    # Verify the backend's raw state cache was updated
    assert "device123" in api._raw_state
    cached_snapshot = api._raw_state["device123"]
    assert cached_snapshot.attrs == test_attrs
    assert cached_snapshot.timestamp > 0

    # Verify WebSocket update tracked
    assert "device123" in coordinator._ws_last_update
    assert coordinator._ws_last_update["device123"] > 0


@pytest.mark.asyncio
async def test_coordinator_websocket_update_produces_typed_status(hass: HomeAssistant):
    """A WebSocket delta for a known device type translates into typed fields
    on coordinator.data, not just raw attrs.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = _make_api()
    api.devices["device123"] = BestwayDevice(
        protocol_version=1,
        device_id="device123",
        product_name="Airjet_V01",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
        backend=BACKEND_GIZWITS,
    )
    assert api.devices["device123"].device_type == BestwayDeviceType.AIRJET_V01_SPA

    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    coordinator.handle_websocket_update(
        "device123", {"power": 1, "Tnow": 30, "Tset": 38}
    )

    status = coordinator.data.devices["device123"]
    assert status.power is True
    assert status.current_temperature == 30
    assert status.target_temperature == 38


@pytest.mark.asyncio
async def test_coordinator_websocket_disconnect(hass: HomeAssistant):
    """Test polling fallback on WebSocket disconnect."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = MagicMock(spec=BestwayApi)
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Set WebSocket active mode (5min polling)
    coordinator.set_websocket_active()
    assert coordinator.update_interval == timedelta(seconds=300)

    # Simulate disconnect
    coordinator.handle_websocket_disconnect()

    # Verify polling reverted to 30s
    assert coordinator.update_interval == timedelta(seconds=30)


@pytest.mark.asyncio
async def test_coordinator_set_websocket_active(hass: HomeAssistant):
    """Test setting coordinator to WebSocket-active mode."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = MagicMock(spec=BestwayApi)
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Initial state: 30s polling
    assert coordinator.update_interval == timedelta(seconds=30)

    # Activate WebSocket mode
    coordinator.set_websocket_active()

    # Verify reduced to 5min
    assert coordinator.update_interval == timedelta(seconds=300)


@pytest.mark.asyncio
async def test_multi_device_websocket_updates(hass: HomeAssistant):
    """Test WebSocket updates work correctly with multiple devices."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = _make_api()
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Update device 1
    coordinator.handle_websocket_update("device1", {"power": 1, "temp_now": 38})

    # Update device 2
    coordinator.handle_websocket_update("device2", {"power": 0, "temp_now": 25})

    # Verify both devices updated independently
    assert "device1" in api._raw_state
    assert "device2" in api._raw_state
    assert api._raw_state["device1"].attrs["power"] == 1
    assert api._raw_state["device1"].attrs["temp_now"] == 38
    assert api._raw_state["device2"].attrs["power"] == 0
    assert api._raw_state["device2"].attrs["temp_now"] == 25


@pytest.mark.asyncio
async def test_websocket_update_creates_device_status(hass: HomeAssistant):
    """Test WebSocket update creates a raw state entry correctly."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = _make_api()
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Record time before update
    before_time = int(time())

    # Simulate WebSocket update
    coordinator.handle_websocket_update("device_abc", {"power": 1})

    # Verify the raw snapshot was created with a current timestamp
    snapshot = api._raw_state["device_abc"]
    assert snapshot.timestamp >= before_time
    assert snapshot.timestamp <= int(time())
    assert snapshot.attrs == {"power": 1}


@pytest.mark.asyncio
async def test_coordinator_tracks_websocket_update_times(hass: HomeAssistant):
    """Test coordinator tracks last WebSocket update time per device."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = _make_api()
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Initially no tracked updates
    assert len(coordinator._ws_last_update) == 0

    # Update device
    coordinator.handle_websocket_update("device1", {"power": 1})

    # Verify update time tracked
    assert "device1" in coordinator._ws_last_update
    update_time = coordinator._ws_last_update["device1"]
    assert update_time > 0

    # Update again
    await asyncio.sleep(0.01)  # Small delay
    coordinator.handle_websocket_update("device1", {"power": 0})

    # Verify time updated
    new_update_time = coordinator._ws_last_update["device1"]
    assert new_update_time > update_time
