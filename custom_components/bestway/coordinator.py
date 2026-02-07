"""Data update coordinator for the Bestway API."""

import asyncio
from datetime import timedelta
from logging import getLogger
from time import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aws_iot.api import AwsIotApi
from .aws_iot.websocket import AwsIotWebSocket
from .bestway.api import BestwayApi, BestwayApiResults
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
        async with asyncio.timeout(10):
            await self.api.refresh_bindings()
            return await self.api.fetch_data()

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
