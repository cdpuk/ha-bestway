"""Data update coordinator for the Bestway API."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from logging import getLogger
from time import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aws_iot.api import AwsIotApi, AwsIotAuthException
from .aws_iot.websocket import AwsIotWebSocket
from .bestway.api import BestwayApi, BestwayApiResults, BestwayAuthException
from .bestway.model import BestwayDeviceStatus
from .bestway.websocket import GizwitsWebSocket

_LOGGER = getLogger(__name__)


class BestwayUpdateCoordinator(DataUpdateCoordinator[BestwayApiResults]):
    """Update coordinator that polls the device status for all devices in an account."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: BestwayApi | AwsIotApi,
        reauth_callback: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        """Initialize my coordinator.

        Args:
            reauth_callback: Called to obtain a fresh auth token when the API
                reports the current one is invalid. Should update the API
                instance and config entry in place, or raise if credentials
                are no longer valid (e.g. password changed), which converts
                to ConfigEntryAuthFailed and triggers HA's reauth flow.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Bestway API",
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self._reauth_callback = reauth_callback
        self._ws_last_update: dict[str, float] = {}  # Track WebSocket update times
        self.websocket: GizwitsWebSocket | None = None
        self.websockets: list[AwsIotWebSocket] = []

    async def _async_update_data(self) -> BestwayApiResults:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            async with asyncio.timeout(10):
                await self.api.refresh_bindings()
                return await self.api.fetch_data()
        except (BestwayAuthException, AwsIotAuthException) as err:
            return await self._async_handle_auth_failure(err)

    async def _async_handle_auth_failure(
        self, original_err: Exception
    ) -> BestwayApiResults:
        """Attempt to recover from an auth token that the server has invalidated.

        Cloud tokens can expire or be revoked server-side without warning
        (observed after a couple of days of continuous use). Rather than
        failing silently forever and leaving entities unavailable until the
        user removes and re-adds the integration, try to obtain a fresh
        token and retry once. Only genuine credential failures escalate to
        ConfigEntryAuthFailed, which prompts HA's reauth flow. The retry
        gets its own timeout budget, separate from the failed first attempt.
        """
        if self._reauth_callback is None:
            raise ConfigEntryAuthFailed from original_err

        _LOGGER.warning(
            "Auth token rejected by server, attempting to refresh: %s", original_err
        )
        try:
            await self._reauth_callback()
        except Exception as reauth_err:  # pylint: disable=broad-except
            _LOGGER.error("Failed to refresh auth token: %s", reauth_err)
            raise ConfigEntryAuthFailed from reauth_err

        try:
            async with asyncio.timeout(10):
                await self.api.refresh_bindings()
                return await self.api.fetch_data()
        except (BestwayAuthException, AwsIotAuthException) as err:
            # Refreshed token was rejected again - credentials are stale
            _LOGGER.error("Refreshed auth token was also rejected: %s", err)
            raise ConfigEntryAuthFailed from err

    def handle_websocket_update(self, device_id: str, attrs: dict[str, Any]) -> None:
        """Handle real-time device update from WebSocket.

        Updates the device state cache with real-time data from WebSocket
        and triggers immediate entity updates. This provides sub-second
        update latency compared to 30-second polling.

        Args:
            device_id: Device ID (DID) that was updated
            attrs: Device attributes from WebSocket s2c_noti message
        """
        _LOGGER.debug(
            "WebSocket update for device %s with %d attributes", device_id, len(attrs)
        )

        # Merge WebSocket updates with existing state to preserve diagnostic fields
        # WebSocket deltas only include changed fields, not full state
        existing = self.api._state_cache.get(device_id)
        if existing:
            merged_attrs = {**existing.attrs, **attrs}
        else:
            merged_attrs = attrs

        # Update state cache with merged data
        self.api._state_cache[device_id] = BestwayDeviceStatus(
            timestamp=int(time()),
            attrs=merged_attrs,
        )

        # Track last WebSocket update time for this device
        self._ws_last_update[device_id] = time()

        # Trigger immediate entity updates
        self.async_set_updated_data(BestwayApiResults(self.api._state_cache))

    def handle_websocket_disconnect(self) -> None:
        """Handle WebSocket disconnection.

        Increases polling frequency to 30 seconds as fallback when
        WebSocket connection is lost. This ensures the integration
        continues functioning reliably even without real-time updates.
        """
        _LOGGER.warning("WebSocket disconnected, reverting to 30-second polling")
        self.update_interval = timedelta(seconds=30)

    def set_websocket_active(self) -> None:
        """Set polling interval for WebSocket-active mode.

        Reduces polling frequency to 5 minutes when WebSocket is providing
        real-time updates. Polling continues as a safety net to catch any
        missed updates or handle WebSocket connection issues.
        """
        _LOGGER.info("WebSocket active, reducing polling to 5-minute intervals")
        self.update_interval = timedelta(seconds=300)
