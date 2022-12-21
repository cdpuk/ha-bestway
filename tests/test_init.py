"""Test bestway setup process."""
from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.exceptions import ConfigEntryNotReady
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bestway import (
    BestwayUpdateCoordinator,
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.bestway.const import (
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_USER_TOKEN,
    CONF_USER_TOKEN_EXPIRY,
    CONF_USERNAME,
    DOMAIN,
)


async def test_setup_unload_and_reload_entry(hass, bypass_get_data):
    """Test entry setup and unload."""

    # This config entry has an auth token that expires far enough in
    # the future that no auth attempt should be made
    future = (datetime.now() + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
        },
        entry_id="test",
    )

    # Set up the entry and assert that the values set during setup are where we expect
    # them to be. Because we have patched the BestwayUpdateCoordinator.async_get_data
    # call, no code from custom_components/bestway/api.py actually runs.
    with patch(
        "custom_components.bestway.bestway.BestwayApi.get_user_token"
    ) as get_user_token_fn:
        assert await async_setup_entry(hass, config_entry)

    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # The token expires far enough in the future that a call to refresh
    # the token should not be made.
    get_user_token_fn.assert_not_called()

    # Reload the entry and assert that the data from above is still there
    assert await async_reload_entry(hass, config_entry) is None
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # Unload the entry and verify that the data has been removed
    assert await async_unload_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_expired_token(hass, bypass_get_data):
    """Test what happens when the auth token needs to be refreshed."""

    # This config entry has an auth token that needs renewal (<30 days)
    future = (datetime.now() + timedelta(days=15)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
        },
        entry_id="test",
    )

    with patch("custom_components.bestway.bestway.BestwayApi.get_user_token") as p:
        await async_setup_entry(hass, config_entry)
        p.assert_called_once()


async def test_setup_entry_exception(hass, error_on_get_data):
    """Test ConfigEntryNotReady when API raises an exception during entry setup."""

    # This config entry has an auth token that expires in the future
    future = (datetime.now() + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
        },
        entry_id="test",
    )

    with pytest.raises(ConfigEntryNotReady):
        assert await async_setup_entry(hass, config_entry)
