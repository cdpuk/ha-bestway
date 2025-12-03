"""Integration tests for WebSocket coordinator callbacks."""

from datetime import timedelta
from time import time
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bestway.bestway.api import BestwayApi
from custom_components.bestway.bestway.model import BestwayDeviceStatus
from custom_components.bestway.const import CONF_API_ROOT, CONF_API_ROOT_EU, DOMAIN
from custom_components.bestway.coordinator import BestwayUpdateCoordinator


@pytest.mark.asyncio
async def test_coordinator_websocket_update(hass: HomeAssistant):
    """Test coordinator receives and processes WebSocket updates."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    # Create mock API
    api = MagicMock(spec=BestwayApi)
    api._state_cache = {}

    # Create coordinator
    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Simulate WebSocket update
    test_attrs = {
        "power": 1,
        "temp_now": 36,
        "temp_set": 38,
        "heat_power": 1,
    }

    coordinator.handle_websocket_update("device123", test_attrs)

    # Verify state cache updated
    assert "device123" in api._state_cache
    cached_status = api._state_cache["device123"]
    assert isinstance(cached_status, BestwayDeviceStatus)
    assert cached_status.attrs == test_attrs
    assert cached_status.timestamp > 0

    # Verify WebSocket update tracked
    assert "device123" in coordinator._ws_last_update
    assert coordinator._ws_last_update["device123"] > 0


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

    api = MagicMock(spec=BestwayApi)
    api._state_cache = {}

    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Update device 1
    coordinator.handle_websocket_update("device1", {"power": 1, "temp_now": 38})

    # Update device 2
    coordinator.handle_websocket_update("device2", {"power": 0, "temp_now": 25})

    # Verify both devices updated independently
    assert "device1" in api._state_cache
    assert "device2" in api._state_cache
    assert api._state_cache["device1"].attrs["power"] == 1
    assert api._state_cache["device1"].attrs["temp_now"] == 38
    assert api._state_cache["device2"].attrs["power"] == 0
    assert api._state_cache["device2"].attrs["temp_now"] == 25


@pytest.mark.asyncio
async def test_websocket_update_creates_device_status(hass: HomeAssistant):
    """Test WebSocket update creates BestwayDeviceStatus correctly."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = MagicMock(spec=BestwayApi)
    api._state_cache = {}

    coordinator = BestwayUpdateCoordinator(hass, config_entry, api)

    # Record time before update
    before_time = int(time())

    # Simulate WebSocket update
    coordinator.handle_websocket_update("device_abc", {"power": 1})

    # Verify BestwayDeviceStatus created with current timestamp
    status = api._state_cache["device_abc"]
    assert status.timestamp >= before_time
    assert status.timestamp <= int(time())
    assert status.attrs == {"power": 1}


@pytest.mark.asyncio
async def test_coordinator_tracks_websocket_update_times(hass: HomeAssistant):
    """Test coordinator tracks last WebSocket update time per device."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_ROOT: CONF_API_ROOT_EU},
        entry_id="test",
    )

    api = MagicMock(spec=BestwayApi)
    api._state_cache = {}

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
    import time as time_module

    time_module.sleep(0.01)  # Small delay
    coordinator.handle_websocket_update("device1", {"power": 0})

    # Verify time updated
    new_update_time = coordinator._ws_last_update["device1"]
    assert new_update_time > update_time
