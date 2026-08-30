"""The bestway integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from logging import getLogger

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .bestway.api import BestwayApi
from .bestway.model import BestwayDeviceType
from .bestway.websocket import GizwitsWebSocket
from .const import (
    BACKEND_AWS_IOT,
    BACKEND_GIZWITS,
    BACKEND_SMARTSPA,
    BUBBLES_MODE_3WAY,
    BUBBLES_MODE_DEFAULT,
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_BUBBLES_MODE,
    CONF_PASSWORD,
    CONF_SMARTSPA_ACCOUNT,
    CONF_SMARTSPA_PASSWORD,
    CONF_SMARTSPA_REGION,
    CONF_SMARTSPA_TOKEN,
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


_MODE_DEPENDENT_BUBBLE_TYPES = (
    BestwayDeviceType.AIRJET_V02,
    BestwayDeviceType.ULTRAFIT_AIRJET_V02,
    BestwayDeviceType.HYDROJET_V02,
    BestwayDeviceType.HYDROJET_PRO_V02,
)


def _async_remove_orphaned_bubbles_entities(
    hass: HomeAssistant, entry: ConfigEntry, api
) -> None:
    """Remove the bubbles control left over from the other bubbles mode.

    The bubbles-mode option swaps between a 3-way select
    (unique_id ``<device>_bubbles``) and an on/off switch
    (``<device>_spa_wave_power``). Whichever one the current mode does not
    create would otherwise linger in the entity registry as a dead
    "restored" entity after every mode change. Only the V02 device types
    whose control is mode-dependent are touched; V01 devices always keep
    their select.
    """
    registry = er.async_get(hass)
    mode = entry.options.get(CONF_BUBBLES_MODE, BUBBLES_MODE_DEFAULT)
    stale_suffix = "_spa_wave_power" if mode == BUBBLES_MODE_3WAY else "_bubbles"
    stale_ids = {
        f"{device_id}{stale_suffix}"
        for device_id, device in api.devices.items()
        if device.device_type in _MODE_DEPENDENT_BUBBLE_TYPES
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in stale_ids:
            _LOGGER.debug(
                "Removing orphaned bubbles entity %s (mode change)",
                entity.entity_id,
            )
            registry.async_remove(entity.entity_id)


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
    elif backend == BACKEND_SMARTSPA:
        # SmartSpa gateway (post-July-2026 Bestway Connect, account login)
        return await _async_setup_smartspa(hass, entry, session)
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
    expiry_cutoff = (datetime.now(UTC) + timedelta(days=30)).timestamp()
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
                    # Only drop to 5-minute polling once the socket actually
                    # connects; if it never does (e.g. blocked by a firewall),
                    # the coordinator keeps polling every 30 seconds.
                    connect_callback=coordinator.set_websocket_active,
                )

                # Connect as a background task. Unlike hass.async_create_task,
                # this is not awaited during HA's startup wrap-up, so a
                # connection that hangs or retries indefinitely (e.g. because
                # the device is unreachable) cannot block startup. It is
                # cancelled automatically when the config entry unloads.
                entry.async_create_background_task(
                    hass, ws_client.connect(), name=f"{DOMAIN}-websocket"
                )

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

    _async_remove_orphaned_bubbles_entities(hass, entry, api)

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

    # Always request a fresh token on startup.
    # Stored tokens expire server-side without warning, and the API has no
    # expiry field we can check. Re-authenticating is cheap (one POST) and
    # avoids the "Token is not authorized" failure that leaves all entities
    # unavailable until the next HA restart.
    try:
        token = await AwsIotApi.authenticate(session, visitor_id, location, api_base)
        # Update entry with fresh token
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
                    # Only drop to 5-minute polling once a socket actually
                    # connects; if none do (e.g. blocked by a firewall), the
                    # coordinator keeps polling every 30 seconds.
                    connect_callback=coordinator.set_websocket_active,
                )

                # Connect as a background task. Unlike hass.async_create_task,
                # this is not awaited during HA's startup wrap-up, so a
                # connection that hangs or retries indefinitely (e.g. because
                # the device is unreachable) cannot block startup. It is
                # cancelled automatically when the config entry unloads.
                entry.async_create_background_task(
                    hass, ws.connect(), name=f"{DOMAIN}-websocket-{device_id[:12]}"
                )
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
    else:
        _LOGGER.warning("No devices found, WebSocket not initialized")

    # Store WebSockets list on coordinator
    coordinator.websockets = websockets

    _async_remove_orphaned_bubbles_entities(hass, entry, api)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def _async_setup_smartspa(
    hass: HomeAssistant, entry: ConfigEntry, session: ClientSession
) -> bool:
    """Set up the SmartSpa gateway backend (account login, polling only).

    No WebSocket path is known for this gateway yet; the 30-second polling
    default of the coordinator applies. The API client transparently
    re-authenticates when the gateway invalidates the token (code 505).
    """
    from .smartspa.api import (
        SMARTSPA_ENDPOINTS,
        SmartSpaApi,
        SmartSpaAuthException,
        SmartSpaException,
    )

    account = str(entry.data[CONF_SMARTSPA_ACCOUNT])
    password = str(entry.data[CONF_SMARTSPA_PASSWORD])
    region = str(entry.data.get(CONF_SMARTSPA_REGION, "EU"))
    api_base = SMARTSPA_ENDPOINTS.get(region, SMARTSPA_ENDPOINTS["EU"])

    _LOGGER.info("Initializing SmartSpa API for %s (%s)", account, api_base)

    # Reuse the stored token when there is one: the client re-authenticates
    # transparently on code 505, so a stale token costs one retried request
    # rather than a failed setup, and reloads/restarts avoid a redundant
    # login round-trip.
    token = entry.data.get(CONF_SMARTSPA_TOKEN)
    if not token:
        try:
            token = await SmartSpaApi.authenticate(session, account, password, api_base)
        except SmartSpaAuthException as ex:
            _LOGGER.error("SmartSpa authentication failed: %s", ex)
            raise ConfigEntryAuthFailed from ex
        except SmartSpaException as ex:
            raise ConfigEntryNotReady from ex
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_SMARTSPA_TOKEN: token}
        )

    api = SmartSpaApi(session, account, password, api_base, token)

    coordinator = BestwayUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    if not api.devices:
        _LOGGER.warning("SmartSpa account %s has no devices", account)

    _async_remove_orphaned_bubbles_entities(hass, entry, api)

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
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is None:
            return unload_ok

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
    """Reload config entry.

    Delegate to the config-entries framework rather than calling
    unload/setup directly: the framework tracks entry state and retries
    ConfigEntryNotReady with backoff, so a transient failure during an
    options reload recovers by itself instead of leaving every entity
    unavailable until the next restart.
    """
    await hass.config_entries.async_reload(entry.entry_id)


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
