"""Data update coordinator for the Bestway API."""

import asyncio
from datetime import timedelta
from logging import getLogger
from time import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aws_iot.websocket import AwsIotWebSocket
from .backend import BackendApi
from .bestway.websocket import GizwitsWebSocket
from .model import BestwayApiResults
from .smartspa.api import SmartSpaAuthException

_LOGGER = getLogger(__name__)


class BestwayUpdateCoordinator(DataUpdateCoordinator[BestwayApiResults]):
    """Update coordinator that polls the device status for all devices in an account."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: BackendApi,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Bestway API",
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self._ws_last_update: dict[str, float] = {}  # Track WebSocket update times
        self.websocket: GizwitsWebSocket | None = None
        self.websockets: list[AwsIotWebSocket] = []

    async def _async_update_data(self) -> BestwayApiResults:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        # 30s (was 10s): the SmartSpa backend may transparently re-login and
        # retry inside a poll cycle, and 10s was already reported as too tight
        # for slow paths to Bestway's cloud (upstream PR #137).
        try:
            async with asyncio.timeout(30):
                await self.api.refresh_bindings()
                return await self.api.fetch_data()
        except SmartSpaAuthException as err:
            # Re-login already failed inside the API; the stored credentials no
            # longer work. A re-auth config flow is out of scope for now, but HA
            # should at least surface this as an auth problem rather than a
            # generic update failure.
            raise ConfigEntryAuthFailed(str(err)) from err

    def handle_websocket_update(self, device_id: str, attrs: dict[str, Any]) -> None:
        """Handle real-time device update from WebSocket.

        Delegates the merge-and-translate work to the backend, which owns
        the raw state cache these deltas are partial updates against, then
        triggers immediate entity updates. This provides sub-second update
        latency compared to 30-second polling.

        Args:
            device_id: Device ID (DID) that was updated
            attrs: Device attributes from WebSocket s2c_noti message
        """
        _LOGGER.debug(
            "WebSocket update for device %s with %d attributes", device_id, len(attrs)
        )

        results = self.api.handle_partial_update(device_id, attrs)

        # Track last WebSocket update time for this device
        self._ws_last_update[device_id] = time()

        # Trigger immediate entity updates
        self.async_set_updated_data(results)

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
