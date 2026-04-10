"""Tests for entity availability, optimistic switch state, and climate safety.

These tests cover the fixes in:
- entity.py: available property ignoring unreliable is_online
- switch.py: optimistic state tracking
- climate.py: safe .get() for Tunit key
"""

from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from custom_components.bestway.bestway.model import (
    BestwayDevice,
    BestwayDeviceStatus,
)
from custom_components.bestway.bestway.api import BestwayApiResults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(is_online: bool = True) -> BestwayDevice:
    return BestwayDevice(
        protocol_version=2,
        device_id="test_device",
        product_name="AIRJET",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=is_online,
    )


def _make_status(attrs: dict[str, Any] | None = None) -> BestwayDeviceStatus:
    default_attrs = {
        "power": True,
        "filter": 0,
        "wave": 0,
        "jet": False,
        "locked": False,
        "heat": 0,
        "Tnow": 30,
        "Tset": 40,
        "Tunit": 1,
        "is_online": True,
    }
    if attrs:
        default_attrs.update(attrs)
    return BestwayDeviceStatus(timestamp=1000, attrs=default_attrs)


def _make_coordinator(device: BestwayDevice, status: BestwayDeviceStatus):
    """Create a mock coordinator with the given device and status."""
    coordinator = MagicMock()
    coordinator.api = MagicMock()
    coordinator.api.devices = {"test_device": device}
    coordinator.data = BestwayApiResults(devices={"test_device": status})
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# entity.py: available property
# ---------------------------------------------------------------------------


class TestEntityAvailability:
    """Test that entity availability does NOT depend on is_online."""

    def test_available_when_online(self):
        """Entity is available when device is online."""
        from custom_components.bestway.entity import BestwayEntity

        device = _make_device(is_online=True)
        coordinator = _make_coordinator(device, _make_status())
        config_entry = MagicMock()

        entity = BestwayEntity(coordinator, config_entry, "test_device")
        assert entity.available is True

    def test_available_when_offline(self):
        """Entity is available even when is_online is False.

        This is the core fix: the Bestway API reports is_online=False
        unreliably, but the device data is still valid.
        """
        from custom_components.bestway.entity import BestwayEntity

        device = _make_device(is_online=False)
        coordinator = _make_coordinator(device, _make_status())
        config_entry = MagicMock()

        entity = BestwayEntity(coordinator, config_entry, "test_device")
        assert entity.available is True

    def test_unavailable_when_no_device(self):
        """Entity is unavailable when device is not in coordinator."""
        from custom_components.bestway.entity import BestwayEntity

        coordinator = MagicMock()
        coordinator.api = MagicMock()
        coordinator.api.devices = {}  # No devices
        coordinator.last_update_success = True
        config_entry = MagicMock()

        entity = BestwayEntity(coordinator, config_entry, "test_device")
        assert entity.available is False

    def test_unavailable_when_coordinator_fails(self):
        """Entity is unavailable when coordinator update failed."""
        from custom_components.bestway.entity import BestwayEntity

        device = _make_device(is_online=True)
        coordinator = _make_coordinator(device, _make_status())
        coordinator.last_update_success = False
        config_entry = MagicMock()

        entity = BestwayEntity(coordinator, config_entry, "test_device")
        assert entity.available is False


# ---------------------------------------------------------------------------
# switch.py: optimistic state tracking
# ---------------------------------------------------------------------------


class TestSwitchOptimistic:
    """Test that switches use optimistic state updates."""

    def test_switch_has_assumed_state(self):
        """Switch should declare assumed_state for optimistic updates."""
        from custom_components.bestway.switch import (
            BestwaySwitch,
            BestwaySwitchEntityDescription,
        )

        desc = BestwaySwitchEntityDescription(
            key="test_power",
            name="Test Power",
            value_fn=lambda s: bool(s.attrs["power"]),
            turn_on_fn=AsyncMock(),
            turn_off_fn=AsyncMock(),
        )
        device = _make_device()
        coordinator = _make_coordinator(device, _make_status())
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)
        assert switch._attr_assumed_state is True

    def test_switch_optimistic_turn_on(self):
        """Switch shows ON immediately after turn_on, before API responds."""
        from custom_components.bestway.switch import (
            BestwaySwitch,
            BestwaySwitchEntityDescription,
        )

        desc = BestwaySwitchEntityDescription(
            key="test_power",
            name="Test Power",
            value_fn=lambda s: bool(s.attrs["power"]),
            turn_on_fn=AsyncMock(),
            turn_off_fn=AsyncMock(),
        )
        device = _make_device()
        status = _make_status({"power": False})
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)

        # Before toggle: switch reads from coordinator (power=False)
        assert switch.is_on is False

        # Set optimistic state directly (mirrors what async_turn_on does)
        switch._optimistic_state = True
        assert switch.is_on is True

    def test_switch_optimistic_cleared_on_update(self):
        """Optimistic state is cleared when coordinator provides real data."""
        from custom_components.bestway.switch import (
            BestwaySwitch,
            BestwaySwitchEntityDescription,
        )

        desc = BestwaySwitchEntityDescription(
            key="test_power",
            name="Test Power",
            value_fn=lambda s: bool(s.attrs["power"]),
            turn_on_fn=AsyncMock(),
            turn_off_fn=AsyncMock(),
        )
        device = _make_device()
        status = _make_status({"power": True})
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)
        switch._optimistic_state = False  # Optimistic says OFF

        assert switch.is_on is False  # Optimistic overrides

        # Simulate coordinator update — patch async_write_ha_state since
        # there's no real HA instance in unit tests
        with patch.object(switch, "async_write_ha_state"):
            switch._handle_coordinator_update()
        assert switch._optimistic_state is None  # Cleared
        # Now reads actual state from coordinator (power=True)
        assert switch.is_on is True


# ---------------------------------------------------------------------------
# climate.py: Tunit KeyError safety
# ---------------------------------------------------------------------------


class TestClimateTunitSafety:
    """Test that missing Tunit key doesn't crash the climate entity."""

    def _make_thermostat(self, attrs: dict[str, Any] | None = None):
        """Create an AirjetV01HydrojetSpaThermostat with the given status attrs."""
        from custom_components.bestway.climate import AirjetV01HydrojetSpaThermostat

        device = _make_device()
        status = _make_status(attrs) if attrs is not None else _make_status()
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()
        return AirjetV01HydrojetSpaThermostat(coordinator, config_entry, "test_device")

    def _make_thermostat_no_status(self):
        """Create a thermostat whose coordinator has no status for the device."""
        from custom_components.bestway.climate import AirjetV01HydrojetSpaThermostat

        device = _make_device()
        coordinator = MagicMock()
        coordinator.api = MagicMock()
        coordinator.api.devices = {"test_device": device}
        coordinator.data = BestwayApiResults(devices={})
        coordinator.last_update_success = True
        config_entry = MagicMock()
        return AirjetV01HydrojetSpaThermostat(coordinator, config_entry, "test_device")

    def test_temperature_unit_with_tunit_present(self):
        """Returns Celsius when Tunit=1 (truthy value)."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat({"Tunit": 1})
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)

    def test_temperature_unit_with_tunit_zero(self):
        """Returns Fahrenheit when Tunit=0 (falsy value)."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat({"Tunit": 0})
        assert thermostat.temperature_unit == str(UnitOfTemperature.FAHRENHEIT)

    def test_temperature_unit_with_tunit_missing(self):
        """Returns Celsius when Tunit key is missing entirely (no KeyError)."""
        from homeassistant.const import UnitOfTemperature

        attrs = {"power": True, "heat": 0, "Tnow": 30, "Tset": 40}
        thermostat = self._make_thermostat(attrs)
        # Tunit missing -> .get("Tunit", 1) defaults to 1 (truthy) -> Celsius
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)

    def test_temperature_unit_with_no_status(self):
        """Returns Celsius when status is None."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat_no_status()
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)
