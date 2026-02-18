"""The bestway integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from logging import getLogger

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bestway.api import BestwayApi
from .bestway.websocket import GizwitsWebSocket
from .const import (
    BACKEND_AWS_IOT,
    BACKEND_GIZWITS,
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_UID,
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
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up bestway from a config entry."""

    # Detect backend (default to Gizwits for backwards compatibility)
    backend = entry.data.get("backend", BACKEND_GIZWITS)
    _LOGGER.info("Setting up Bestway integration with %s backend", backend)

    session = async_get_clientsession(hass)

    # Branch based on backend
    if backend == BACKEND_AWS_IOT:
        # AWS IoT V02 backend
        return await _async_setup_aws_iot(hass, entry, session)
    else:
        # Gizwits V01 backend (existing flow)
        return await _async_setup_gizwits(hass, entry, session)


async def _async_setup_gizwits(
    hass: HomeAssistant, entry: ConfigEntry, session: ClientSession
) -> bool:
    """Set up Gizwits V01 backend (existing logic)."""
    username = str(entry.data.get(CONF_USERNAME))
    password = str(entry.data.get(CONF_PASSWORD))
    api_root = str(entry.data.get(CONF_API_ROOT))
    user_token = str(entry.data.get(CONF_USER_TOKEN))
    user_token_expiry = entry.data.get(CONF_USER_TOKEN_EXPIRY)

    if not isinstance(user_token_expiry, int):
        user_token_expiry = 0

    # Check for an auth token
    # If we have one that expires within 30 days, refresh it
    # Also refresh if UID is missing (for WebSocket support)
    expiry_cutoff = (datetime.now() + timedelta(days=30)).timestamp()
    uid = entry.data.get(CONF_UID)

    if user_token and expiry_cutoff < user_token_expiry and uid:
        _LOGGER.info("Reusing existing access token")
    else:
        if not uid:
            _LOGGER.info("UID missing, fetching new token to enable WebSocket")
        else:
            _LOGGER.info("Requesting a new auth token")

        try:
            token = await BestwayApi.get_user_token(
                session, username, password, api_root
            )
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.error("Failed to refresh API token: %s", ex)
            raise ConfigEntryNotReady from ex
        user_token = token.user_token
        user_token_expiry = token.expiry
        uid = token.user_id

        new_config_data = {
            CONF_USER_TOKEN: user_token,
            CONF_USER_TOKEN_EXPIRY: user_token_expiry,
            CONF_UID: uid,
        }

        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **new_config_data}
        )

    api = BestwayApi(session, user_token, api_root)
    coordinator = BestwayUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    # Initialize WebSocket for real-time updates
    # uid variable is set above (either from config or from token refresh)
    ws_client = None

    if uid:
        try:
            # Get WebSocket endpoint from first device
            if api.devices:
                first_device = next(iter(api.devices.values()))

                ws_client = GizwitsWebSocket(
                    uid=uid,
                    token=user_token,
                    ws_host=first_device.ws_host,
                    ws_port=first_device.ws_port,
                    update_callback=coordinator.handle_websocket_update,
                    disconnect_callback=coordinator.handle_websocket_disconnect,
                )

                # Connect in background
                hass.async_create_task(ws_client.connect())

                # Reduce polling now that WebSocket will provide real-time updates
                coordinator.set_websocket_active()

                _LOGGER.info("WebSocket client initialized")
            else:
                _LOGGER.warning("No devices found, WebSocket not initialized")
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Failed to setup WebSocket, falling back to polling: %s", ex
            )
    else:
        _LOGGER.info("No UID in config, WebSocket disabled (polling only)")

    # Store WebSocket on coordinator to avoid data structure change
    coordinator.websocket = ws_client

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def _async_setup_aws_iot(
    hass: HomeAssistant, entry: ConfigEntry, session: ClientSession
) -> bool:
    """Set up AWS IoT V02 backend."""
    from .aws_iot.api import AwsIotApi, AwsIotAuthException
    from .aws_iot.websocket import AwsIotWebSocket

    visitor_id = entry.data["visitor_id"]
    token = entry.data.get("token")
    location = entry.data.get("location", "GB")
    api_base = entry.data.get("api_base")  # Regional endpoint from config flow

    # Fallback for existing configs without api_base
    if not api_base:
        from .aws_iot.api import API_ENDPOINTS

        region = entry.data.get("region", "EU")
        api_base = API_ENDPOINTS.get(region, API_ENDPOINTS["EU"])

    _LOGGER.info(
        "Initializing AWS IoT API for visitor %s (endpoint: %s)",
        visitor_id[:12],
        api_base,
    )

    # Initialize API
    api = AwsIotApi(session, visitor_id, token, location, api_base)

    # Authenticate if token missing or refresh if needed
    if not token:
        try:
            token = await AwsIotApi.authenticate(
                session, visitor_id, location, api_base
            )
            # Update entry with token
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": token}
            )
            api._token = token
        except AwsIotAuthException as ex:
            _LOGGER.error("AWS IoT authentication failed: %s", ex)
            raise ConfigEntryAuthFailed from ex

    # Initialize coordinator
    coordinator = BestwayUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    # Initialize per-device WebSockets
    websockets = []
    if api.devices:
        for device_id, device in api.devices.items():
            try:
                # Token refresh callback
                async def token_refresh_callback() -> str:
                    new_token = await AwsIotApi.authenticate(
                        session, visitor_id, location, api_base
                    )
                    api._token = new_token
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "token": new_token}
                    )
                    return new_token

                ws = AwsIotWebSocket(
                    device_id=device_id,
                    service_region=device.ws_host,  # Region stored in ws_host
                    token=token,
                    update_callback=coordinator.handle_websocket_update,
                    disconnect_callback=coordinator.handle_websocket_disconnect,
                    token_refresh_callback=token_refresh_callback,
                )

                # Connect in background
                hass.async_create_task(ws.connect())
                websockets.append(ws)

                _LOGGER.info(
                    "WebSocket initialized for device %s (region: %s)",
                    device_id[:12],
                    device.ws_host,
                )

            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.warning(
                    "Failed to setup WebSocket for device %s: %s", device_id[:12], ex
                )

        # Reduce polling with WebSocket active
        coordinator.set_websocket_active()
    else:
        _LOGGER.warning("No devices found, WebSocket not initialized")

    # Store WebSockets list on coordinator
    coordinator.websockets = websockets

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
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Cleanup WebSocket connection(s)
        # Gizwits: Single websocket
        if coordinator.websocket:
            await coordinator.websocket.disconnect()
            _LOGGER.info("Gizwits WebSocket disconnected")

        # AWS IoT: Multiple websockets (list)
        if coordinator.websockets:
            for ws in coordinator.websockets:
                try:
                    await ws.disconnect()
                except Exception as ex:
                    _LOGGER.warning("Error disconnecting WebSocket: %s", ex)
            _LOGGER.info(
                "AWS IoT WebSockets disconnected (%d devices)",
                len(coordinator.websockets),
            )

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
        hass.config_entries.async_update_entry(entry, data=new, version=2)

        _LOGGER.info("Migration to version %s successful", entry.version)
        return True

    _LOGGER.error("Existing schema version %s is not supported", entry.version)
    return False
