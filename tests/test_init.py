"""Test bestway setup process."""
from homeassistant.exceptions import ConfigEntryNotReady
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bestway import (
    BestwayUpdateCoordinator,
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.bestway.const import DOMAIN

from .const import MOCK_CONFIG


async def test_setup_unload_and_reload_entry(hass, bypass_auth, bypass_get_data):
    """Test entry setup and unload."""
    # Create a mock entry so we don't have to go through config flow
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")

    # Set up the entry and assert that the values set during setup are where we expect
    # them to be. Because we have patched the GivEnergyUpdateCoordinator.async_get_data
    # call, no code from custom_components/bestway/api.py actually runs.
    assert await async_setup_entry(hass, config_entry)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # Reload the entry and assert that the data from above is still there
    assert await async_reload_entry(hass, config_entry) is None
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # Unload the entry and verify that the data has been removed
    assert await async_unload_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_exception(hass, error_on_get_data):
    """Test ConfigEntryNotReady when API raises an exception during entry setup."""
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")

    with pytest.raises(ConfigEntryNotReady):
        assert await async_setup_entry(hass, config_entry)
