"""The bestway integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from logging import getLogger

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bestway.api import BestwayApi
from .const import (
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_USER_TOKEN,
    CONF_USER_TOKEN_EXPIRY,
    CONF_USERNAME,
    DOMAIN,
)
from .coordinator import BestwayUpdateCoordinator

_LOGGER = getLogger(__name__)
_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up bestway from a config entry."""
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    api_root = entry.data.get(CONF_API_ROOT)
    user_token = entry.data.get(CONF_USER_TOKEN)
    user_token_expiry = int(entry.data.get(CONF_USER_TOKEN_EXPIRY))

    session = async_get_clientsession(hass)

    # Check for an auth token
    # If we have one that expires within 30 days, refresh it
    expiry_cutoff = (datetime.now() + timedelta(days=30)).timestamp()

    if user_token and expiry_cutoff < user_token_expiry:
        _LOGGER.info("Reusing existing access token")
    else:
        _LOGGER.info("Requesting a new auth token")
        try:
            token = await BestwayApi.get_user_token(
                session, username, password, api_root
            )
        except Exception as ex:  # pylint: disable=broad-except
            raise ConfigEntryNotReady from ex
        user_token = token.user_token
        user_token_expiry = token.expiry

        new_config_data = {
            CONF_USER_TOKEN: user_token,
            CONF_USER_TOKEN_EXPIRY: user_token_expiry,
        }

        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **new_config_data}
        )

    api = BestwayApi(session, user_token, api_root)
    coordinator = BestwayUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok: bool = await hass.config_entries.async_unload_platforms(
        entry, _PLATFORMS
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrates old config versions to the latest."""

    _LOGGER.debug("Migrating from version %s", entry.version)

    if entry.version == 1:
        # API root needs to be set
        # In version 1, this was hard coded to the EU endpoint
        new = {**entry.data}
        new[CONF_API_ROOT] = CONF_API_ROOT_EU
        entry.version = 2
        hass.config_entries.async_update_entry(entry, data=new)

        _LOGGER.info("Migration to version %s successful", entry.version)
        return True

    _LOGGER.error("Existing schema version %s is not supported", entry.version)
    return False
