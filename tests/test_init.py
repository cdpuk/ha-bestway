"""Test bestway setup process."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bestway import (
    BestwayUpdateCoordinator,
)
from custom_components.bestway.bestway.model import BestwayUserToken
from custom_components.bestway.const import (
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_UID,
    CONF_USER_TOKEN,
    CONF_USER_TOKEN_EXPIRY,
    CONF_USERNAME,
    DOMAIN,
)
from custom_components.bestway.model import BestwayDevice


async def test_setup_unload_and_reload_entry(hass: HomeAssistant, bypass_get_data):
    """Test entry setup and unload."""

    # This config entry has an auth token that expires far enough in
    # the future that no auth attempt should be made
    future = (datetime.now(UTC) + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
            CONF_UID: "test_uid_123",  # Required to prevent token refresh
        },
        version=2,
        entry_id="test",
    )
    config_entry.add_to_hass(hass)

    # Set up the entry and assert that the values set during setup are where we expect
    # them to be. Because we have patched the BestwayUpdateCoordinator.async_get_data
    # call, no code from custom_components/bestway/api.py actually runs.
    with patch(
        "custom_components.bestway.bestway.api.BestwayApi.get_user_token"
    ) as get_user_token_fn:
        await hass.config_entries.async_setup(config_entry.entry_id)

    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # The token expires far enough in the future that a call to refresh
    # the token should not be made.
    get_user_token_fn.assert_not_called()

    # Reload the entry and assert that the data from above is still there

    await hass.config_entries.async_reload(config_entry.entry_id)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert isinstance(
        hass.data[DOMAIN][config_entry.entry_id], BestwayUpdateCoordinator
    )

    # Unload the entry and verify that the data has been removed
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_expired_token(hass: HomeAssistant, bypass_get_data):
    """Test what happens when the auth token needs to be refreshed."""

    # This config entry has an auth token that needs renewal (<30 days)
    future = (datetime.now(UTC) + timedelta(days=15)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
        },
        version=2,
        entry_id="test",
    )
    config_entry.add_to_hass(hass)

    expected_token = BestwayUserToken(user_id="uid", user_token="new_token", expiry=123)

    with patch("custom_components.bestway.bestway.api.BestwayApi.get_user_token") as p:
        p.return_value = expected_token
        await hass.config_entries.async_setup(config_entry.entry_id)
        p.assert_called_once()

    updated_entry = hass.config_entries.async_get_entry(config_entry.entry_id)
    assert updated_entry is not None
    assert updated_entry.data[CONF_USER_TOKEN] == expected_token.user_token
    assert updated_entry.data[CONF_USER_TOKEN_EXPIRY] == expected_token.expiry


async def test_setup_entry_exception(hass: HomeAssistant, error_on_get_data):
    """Test ConfigEntryNotReady when API raises an exception during entry setup."""

    # This config entry has an auth token that expires in the future
    future = (datetime.now(UTC) + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
        },
        version=2,
        entry_id="test",
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)

    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_websocket_connect_failure_does_not_block_startup(
    hass: HomeAssistant,
):
    """Regression test for #133.

    A WebSocket that never connects (e.g. because a firewall silently drops
    outbound packets) must not block Home Assistant startup. Previously the
    connect task was created with `hass.async_create_task`, which is awaited
    during startup wrap-up, combined with a `connect()` implementation that
    never returns on failure (it recurses into an unbounded reconnect loop).
    """
    future = (datetime.now(UTC) + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
            CONF_UID: "test_uid_123",  # Required to prevent token refresh
        },
        version=2,
        entry_id="test",
    )
    config_entry.add_to_hass(hass)

    device = BestwayDevice(
        protocol_version=1,
        device_id="device1",
        product_name="Airjet",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
        ws_host="m2m.gizwits.com",
        ws_port=8880,
    )

    async def fake_refresh_bindings(self):
        self.devices = {"device1": device}

    async def fake_fetch_data(self):
        return {}

    # Simulates a firewall silently dropping outbound packets: the TCP
    # handshake never completes and websockets.connect() never returns.
    async def hanging_connect(*args, **kwargs):
        await asyncio.Event().wait()

    with (
        patch(
            "custom_components.bestway.bestway.api.BestwayApi.refresh_bindings",
            fake_refresh_bindings,
        ),
        patch(
            "custom_components.bestway.bestway.api.BestwayApi.fetch_data",
            fake_fetch_data,
        ),
        patch(
            "custom_components.bestway.bestway.websocket.websockets.connect",
            side_effect=hanging_connect,
        ),
    ):
        # On the old code, this hangs forever: the never-resolving connect()
        # task is awaited by Home Assistant's startup wrap-up.
        async with asyncio.timeout(5):
            await hass.config_entries.async_setup(config_entry.entry_id)
            await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    # The WebSocket never connected, so polling must remain at the default
    # 30-second interval rather than being relaxed to 5 minutes.
    assert coordinator.update_interval == timedelta(seconds=30)


async def test_websocket_uses_background_task(hass: HomeAssistant):
    """The WebSocket connect task must be a background task.

    Background tasks (`ConfigEntry.async_create_background_task`) are
    excluded from Home Assistant's startup wrap-up wait, unlike tasks
    created with `hass.async_create_task`.
    """
    future = (datetime.now(UTC) + timedelta(days=31)).timestamp()
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test@example.org",
            CONF_PASSWORD: "P@asw0rd",
            CONF_API_ROOT: CONF_API_ROOT_EU,
            CONF_USER_TOKEN: "t0k3n",
            CONF_USER_TOKEN_EXPIRY: int(future),
            CONF_UID: "test_uid_123",
        },
        version=2,
        entry_id="test",
    )
    config_entry.add_to_hass(hass)

    device = BestwayDevice(
        protocol_version=1,
        device_id="device1",
        product_name="Airjet",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
        ws_host="m2m.gizwits.com",
        ws_port=8880,
    )

    async def fake_refresh_bindings(self):
        self.devices = {"device1": device}

    async def fake_fetch_data(self):
        return {}

    captured_coros = []

    def fake_create_background_task(self, hass_arg, coro, *args, **kwargs):
        # Avoid a "coroutine was never awaited" warning: we only care that
        # the coroutine was routed through the background-task API, not
        # that it actually runs.
        captured_coros.append(coro)
        coro.close()

    with (
        patch(
            "custom_components.bestway.bestway.api.BestwayApi.refresh_bindings",
            fake_refresh_bindings,
        ),
        patch(
            "custom_components.bestway.bestway.api.BestwayApi.fetch_data",
            fake_fetch_data,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntry.async_create_background_task",
            fake_create_background_task,
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert len(captured_coros) == 1
