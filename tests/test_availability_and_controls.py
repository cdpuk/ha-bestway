"""Tests for entity availability, optimistic switch state, and climate safety.

These tests cover the fixes in:
- entity.py: available property ignoring unreliable is_online
- switch.py: optimistic state tracking
- climate.py: a safe default temperature_unit when status is absent/unknown
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.bestway.model import (
    BestwayApiResults,
    BestwayDevice,
    DeviceStatus,
    TemperatureUnit,
)

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


def _make_status(attrs: dict[str, Any] | None = None) -> DeviceStatus:
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
    return DeviceStatus(timestamp=1000, attrs=default_attrs)


def _make_coordinator(device: BestwayDevice, status: DeviceStatus):
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
        switch._optimistic.set(True)
        assert switch.is_on is True

    def test_switch_optimistic_cleared_when_real_state_matches(self):
        """Optimistic state is cleared once real data confirms what we set."""
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
        # Real state already matches what we optimistically set (True)
        status = _make_status({"power": True})
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)
        switch._optimistic.set(True)

        with patch.object(switch, "async_write_ha_state"):
            switch._handle_coordinator_update()

        assert switch._optimistic.value is None  # Cleared on confirmation
        assert switch.is_on is True  # Reads from coordinator now

    def test_switch_optimistic_kept_when_real_state_lags(self):
        """Optimistic state survives a refresh that hasn't yet caught the change.

        Without this, the UI flickers ON -> OFF -> ON when async_request_refresh
        fires before the Bestway cloud has acked the command and the shadow
        still reports the previous value.
        """
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
        # Shadow still has the old value while the command is in flight
        status = _make_status({"power": False})
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)
        # Setting stamps a fresh timestamp, so the timeout safety net
        # doesn't fire.
        switch._optimistic.set(True)  # User pressed ON

        with patch.object(switch, "async_write_ha_state"):
            switch._handle_coordinator_update()

        assert switch._optimistic.value is True  # Kept, no flicker
        assert switch.is_on is True

    def test_switch_optimistic_cleared_after_timeout(self):
        """Optimistic state is force-cleared if the cloud never confirms.

        Rapid taps or dropped/reordered commands can leave the cloud in a
        state that never matches the user's last optimistic value. Without
        a timeout the switch would stick on the unconfirmed value forever;
        the timeout self-heals the UI back to reality.
        """
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
        # Cloud says OFF, but user's last optimistic value was ON.
        status = _make_status({"power": False})
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        switch = BestwaySwitch(coordinator, config_entry, "test_device", desc)
        switch._optimistic.set(True)
        from time import monotonic

        # Stamp far enough in the past that the timeout has elapsed.
        switch._optimistic._set_at = monotonic() - switch._optimistic._timeout_s - 1

        with patch.object(switch, "async_write_ha_state"):
            switch._handle_coordinator_update()

        assert switch._optimistic.value is None  # Cleared by timeout
        assert switch.is_on is False  # Falls back to real cloud state


# ---------------------------------------------------------------------------
# select.py: bubbles select uses the same optimistic-value machinery
# ---------------------------------------------------------------------------


class TestBubblesSelectOptimistic:
    """The three-way bubbles select shares switch.py's OptimisticValue, so
    it no longer flickers back to the pre-command level on a refresh that
    lands before the cloud has acked async_select_option().

    ThreeWaySpaBubblesSelect.current_option reads the typed
    DeviceStatus.bubbles field (not .attrs, which switch.py's tests use via
    a custom value_fn) - so these statuses set bubbles directly.
    """

    def test_select_shows_new_option_immediately(self):
        """Selecting a level shows it before the API/coordinator responds."""
        from custom_components.bestway.model import BubblesLevel
        from custom_components.bestway.select import ThreeWaySpaBubblesSelect

        device = _make_device()
        status = DeviceStatus(timestamp=1000, bubbles=BubblesLevel.OFF)
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        select = ThreeWaySpaBubblesSelect(coordinator, config_entry, "test_device")
        assert select.current_option == "OFF"

        # Mirrors what async_select_option does, without the awaited API call.
        select._optimistic.set(BubblesLevel.MAX)
        assert select.current_option == "MAX"

    def test_select_optimistic_kept_when_real_state_lags(self):
        """A refresh that hasn't caught up yet must not flicker the select
        back to the old level.
        """
        from custom_components.bestway.model import BubblesLevel
        from custom_components.bestway.select import ThreeWaySpaBubblesSelect

        device = _make_device()
        # Shadow still has the old value while the command is in flight
        status = DeviceStatus(timestamp=1000, bubbles=BubblesLevel.OFF)
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        select = ThreeWaySpaBubblesSelect(coordinator, config_entry, "test_device")
        select._optimistic.set(BubblesLevel.MAX)

        with patch.object(select, "async_write_ha_state"):
            select._handle_coordinator_update()

        assert select._optimistic.value == BubblesLevel.MAX  # Kept, no flicker
        assert select.current_option == "MAX"

    def test_select_optimistic_cleared_when_real_state_matches(self):
        """Optimistic state clears once the cloud confirms the new level."""
        from custom_components.bestway.model import BubblesLevel
        from custom_components.bestway.select import ThreeWaySpaBubblesSelect

        device = _make_device()
        status = DeviceStatus(timestamp=1000, bubbles=BubblesLevel.MAX)
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()

        select = ThreeWaySpaBubblesSelect(coordinator, config_entry, "test_device")
        select._optimistic.set(BubblesLevel.MAX)

        with patch.object(select, "async_write_ha_state"):
            select._handle_coordinator_update()

        assert select._optimistic.value is None  # Cleared on confirmation
        assert select.current_option == "MAX"  # Now reads from the coordinator


# ---------------------------------------------------------------------------
# climate.py: Tunit KeyError safety
# ---------------------------------------------------------------------------


class TestClimateTunitSafety:
    """Test that a missing/unknown temperature_unit renders a safe default."""

    def _make_thermostat(self, temperature_unit: TemperatureUnit | None):
        """Create a SpaThermostat whose status carries the given typed unit."""
        from custom_components.bestway.climate import SpaThermostat

        device = _make_device()
        status = _make_status()
        status.temperature_unit = temperature_unit
        coordinator = _make_coordinator(device, status)
        config_entry = MagicMock()
        return SpaThermostat(coordinator, config_entry, "test_device")

    def _make_thermostat_no_status(self):
        """Create a thermostat whose coordinator has no status for the device."""
        from custom_components.bestway.climate import SpaThermostat

        device = _make_device()
        coordinator = MagicMock()
        coordinator.api = MagicMock()
        coordinator.api.devices = {"test_device": device}
        coordinator.data = BestwayApiResults(devices={})
        coordinator.last_update_success = True
        config_entry = MagicMock()
        return SpaThermostat(coordinator, config_entry, "test_device")

    def test_temperature_unit_celsius(self):
        """Returns Celsius when the typed unit is CELSIUS."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat(TemperatureUnit.CELSIUS)
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)

    def test_temperature_unit_fahrenheit(self):
        """Returns Fahrenheit when the typed unit is FAHRENHEIT."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat(TemperatureUnit.FAHRENHEIT)
        assert thermostat.temperature_unit == str(UnitOfTemperature.FAHRENHEIT)

    def test_temperature_unit_missing_defaults_to_celsius(self):
        """Returns Celsius when the typed unit is unknown (no crash)."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat(None)
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)

    def test_temperature_unit_with_no_status(self):
        """Returns Celsius when status is None."""
        from homeassistant.const import UnitOfTemperature

        thermostat = self._make_thermostat_no_status()
        assert thermostat.temperature_unit == str(UnitOfTemperature.CELSIUS)
