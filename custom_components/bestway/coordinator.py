"""Data update coordinator for the Bestway API."""

import asyncio
from datetime import datetime, timedelta
from logging import getLogger

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .bestway.api import BestwayApi, BestwayApiResults

_LOGGER = getLogger(__name__)
_BINDINGS_REFRESH_INTERVAL = timedelta(minutes=10)


class BestwayUpdateCoordinator(DataUpdateCoordinator[BestwayApiResults]):
    """Update coordinator that polls the device status for all devices in an account."""

    def __init__(self, hass: HomeAssistant, api: BestwayApi) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Bestway API",
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self.last_bindings_refresh = datetime.min

    async def _async_update_data(self) -> BestwayApiResults:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        async with asyncio.timeout(10):
            # Refresh the device list at a slower rate
            # This may help with rate limiting
            if self.last_bindings_refresh + _BINDINGS_REFRESH_INTERVAL < datetime.now():
                await self.api.refresh_bindings()
                self.last_bindings_refresh = datetime.now()
            return await self.api.fetch_data()
