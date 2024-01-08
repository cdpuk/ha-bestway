"""Bestway API."""
from dataclasses import dataclass
import json
from logging import getLogger
from time import time

from typing import Any

from aiohttp import ClientResponse, ClientSession
import async_timeout

from .model import (
    BestwayDevice,
    BestwayDeviceStatus,
    BestwayDeviceType,
    BestwayUserToken,
    HydrojetBubbles,
    HydrojetHeat,
)

_LOGGER = getLogger(__name__)
_HEADERS = {
    "Content-type": "application/json; charset=UTF-8",
    "X-Gizwits-Application-Id": "98754e684ec045528b073876c34c7348",
}
_TIMEOUT = 10


@dataclass
class BestwayApiResults:
    """A snapshot of device status reports returned from the API."""

    devices: dict[str, BestwayDeviceStatus]


class BestwayException(Exception):
    """An exception while using the API."""


class BestwayOfflineException(BestwayException):
    """Device is offline."""

    def __init__(self) -> None:
        """Construct the exception."""
        super().__init__("Device is offline")


class BestwayAuthException(BestwayException):
    """An authentication error."""


class BestwayTokenInvalidException(BestwayAuthException):
    """Auth token is invalid or expired."""


class BestwayUserDoesNotExistException(BestwayAuthException):
    """User does not exist."""


class BestwayIncorrectPasswordException(BestwayAuthException):
    """Password is incorrect."""


async def _raise_for_status(response: ClientResponse) -> None:
    """Raise an exception based on the response."""
    if response.ok:
        return

    # Try to parse out the bestway error code
    try:
        api_error = await response.json()
    except Exception:  # pylint: disable=broad-except
        response.raise_for_status()

    error_code = api_error.get("error_code", 0)
    if error_code == 9004:
        raise BestwayTokenInvalidException()
    if error_code == 9005:
        raise BestwayUserDoesNotExistException()
    if error_code == 9042:
        raise BestwayOfflineException()
    if error_code == 9020:
        raise BestwayIncorrectPasswordException()

    # If we don't understand the error code, provide more detail for debugging
    response.raise_for_status()


class BestwayApi:
    """Bestway API."""

    def __init__(self, session: ClientSession, user_token: str, api_root: str) -> None:
        """Initialize the API with a user token."""
        self._session = session
        self._user_token = user_token
        self._api_root = api_root

        # Maps device IDs to device info
        self.devices: dict[str, BestwayDevice] = {}

        # Cache containing state information for each device received from the API
        # This is used to work around an annoyance where changes to settings via
        # a POST request are not immediately reflected in a subsequent GET request.
        #
        # When updating state via HA, we update the cache and return this value
        # until the API can provide us with a response containing a timestamp
        # more recent than the local update.
        self._state_cache: dict[str, BestwayDeviceStatus] = {}

    @staticmethod
    async def get_user_token(
        session: ClientSession, username: str, password: str, api_root: str
    ) -> BestwayUserToken:
        """
        Login and obtain a user token.

        The server rate-limits requests for this fairly aggressively.
        """
        body = {"username": username, "password": password, "lang": "en"}

        async with async_timeout.timeout(_TIMEOUT):
            response = await session.post(
                f"{api_root}/app/login", headers=_HEADERS, json=body
            )
            await _raise_for_status(response)
            api_data = await response.json()

        return BestwayUserToken(
            api_data["uid"], api_data["token"], api_data["expire_at"]
        )

    async def refresh_bindings(self) -> None:
        """Refresh and store the list of devices available in the account."""
        self.devices = {
            device.device_id: device for device in await self._get_devices()
        }

    async def _get_devices(self) -> list[BestwayDevice]:
        """Get the list of devices available in the account."""
        api_data = await self._do_get(f"{self._api_root}/app/bindings")
        return [
            BestwayDevice(
                raw["protoc"],
                raw["did"],
                raw["product_name"],
                raw["dev_alias"],
                raw["mcu_soft_version"],
                raw["mcu_hard_version"],
                raw["wifi_soft_version"],
                raw["wifi_hard_version"],
                raw["is_online"],
            )
            for raw in api_data["devices"]
        ]

    async def fetch_data(self) -> BestwayApiResults:
        """Fetch the latest data for all devices."""
        for did, device_info in self.devices.items():
            latest_data = await self._do_get(
                f"{self._api_root}/app/devdata/{did}/latest"
            )

            # Get the age of the data according to the API
            api_update_timestamp = latest_data["updated_at"]

            # Zero indicates the device is offline
            # This has been observed after a device was offline for a few months
            if api_update_timestamp == 0:
                # In testing, the 'attrs' dictionary has been observed to be empty
                _LOGGER.debug("No data available for device %s", did)
                continue

            # Work out whether the received API update is more recent than the
            # locally cached state
            local_update_timestamp = 0
            cached_state: BestwayDeviceStatus | None
            if cached_state := self._state_cache.get(did):
                local_update_timestamp = cached_state.timestamp

            # If the API timestamp is more recent, update the cache
            if api_update_timestamp < local_update_timestamp:
                _LOGGER.debug(
                    "Ignoring update for device %s as local data is newer", did
                )
                continue

            _LOGGER.debug("New data received for device %s", did)
            device_attrs = latest_data["attr"]
            self._state_cache[did] = BestwayDeviceStatus(
                latest_data["updated_at"], device_attrs
            )

            attr_dump = json.dumps(device_attrs)

            if device_info.device_type == BestwayDeviceType.UNKNOWN:
                _LOGGER.warning(
                    "Status for unknown device type '%s' returned: %s",
                    device_info.product_name,
                    attr_dump,
                )
            else:
                _LOGGER.debug(
                    "Status for device type '%s' returned: %s",
                    device_info.product_name,
                    attr_dump,
                )

        return BestwayApiResults(self._state_cache)

    async def airjet_spa_set_power(self, device_id: str, power: bool) -> None:
        """Turn the spa on/off."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting power to %s", "ON" if power else "OFF")
        await self._do_control_post(device_id, power=1 if power else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["spa_power"] = power
        if not power:
            # When powering off, all other functions also turn off
            cached_state.attrs["filter_power"] = False
            cached_state.attrs["heat_power"] = False
            cached_state.attrs["wave_power"] = False

    async def airjet_spa_set_filter(self, device_id: str, filtering: bool) -> None:
        """Turn the filter pump on/off on a spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting filter mode to %s", "ON" if filtering else "OFF")
        await self._do_control_post(device_id, filter_power=1 if filtering else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["filter_power"] = filtering
        if filtering:
            cached_state.attrs["spa_power"] = True
        else:
            cached_state.attrs["wave_power"] = False
            cached_state.attrs["heat_power"] = False

    async def airjet_spa_set_heat(self, device_id: str, heat: bool) -> None:
        """
        Turn the heater on/off on a spa device.

        Turning the heater on will also turn on the filter pump.
        """
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting heater mode to %s", "ON" if heat else "OFF")
        await self._do_control_post(device_id, heat_power=1 if heat else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["heat_power"] = heat
        if heat:
            cached_state.attrs["spa_power"] = True
            cached_state.attrs["filter_power"] = True

    async def airjet_spa_set_target_temp(
        self, device_id: str, target_temp: int
    ) -> None:
        """Set the target temperature on a spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting target temperature to %d", target_temp)
        await self._do_control_post(device_id, temp_set=target_temp)
        cached_state.timestamp = int(time())
        cached_state.attrs["temp_set"] = target_temp

    async def airjet_spa_set_locked(self, device_id: str, locked: bool) -> None:
        """Lock or unlock the physical control panel on a spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting lock state to %s", "ON" if locked else "OFF")
        await self._do_control_post(device_id, locked=1 if locked else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["locked"] = locked

    async def airjet_spa_set_bubbles(self, device_id: str, bubbles: bool) -> None:
        """Turn the bubbles on/off on an Airjet spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting bubbles mode to %s", "ON" if bubbles else "OFF")
        await self._do_control_post(device_id, wave_power=1 if bubbles else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["wave_power"] = bubbles
        if bubbles:
            cached_state.attrs["spa_power"] = True

    async def airjet_v01_spa_set_bubbles(self, device_id: str, bubbles: bool) -> None:
        """Turn the bubbles on/off on an Airjet V01 spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting bubbles mode to %s", "ON" if bubbles else "OFF")
        await self._do_control_post(device_id, wave=1 if bubbles else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["wave"] = bubbles
        if bubbles:
            cached_state.attrs["power"] = True

    async def hydrojet_spa_set_power(self, device_id: str, power: bool) -> None:
        """Turn the spa on/off."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting power to %s", "ON" if power else "OFF")
        await self._do_control_post(device_id, power=1 if power else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["power"] = power
        if not power:
            # When powering off, all other functions also turn off
            cached_state.attrs["filter"] = False
            cached_state.attrs["heat"] = False
            cached_state.attrs["wave"] = HydrojetBubbles.OFF

    async def hydrojet_spa_set_filter(self, device_id: str, filtering: bool) -> None:
        """Turn the filter pump on/off on a spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting filter mode to %s", "ON" if filtering else "OFF")
        await self._do_control_post(device_id, filter=1 if filtering else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["filter"] = filtering
        if filtering:
            cached_state.attrs["power"] = True
        else:
            cached_state.attrs["wave"] = HydrojetBubbles.OFF
            cached_state.attrs["heat"] = False

    async def hydrojet_spa_set_heat(self, device_id: str, heat: bool) -> None:
        """
        Turn the heater on/off on a Hydrojet spa device.

        Turning the heater on will also turn on the filter pump.
        """
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting heater mode to %s", "ON" if heat else "OFF")
        await self._do_control_post(device_id, heat=HydrojetHeat.ON if heat else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["heat"] = heat
        if heat:
            cached_state.attrs["power"] = True
            cached_state.attrs["filter"] = HydrojetHeat.ON

    async def hydrojet_spa_set_target_temp(
        self, device_id: str, target_temp: int
    ) -> None:
        """Set the target temperature on a Hydrojet spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting target temperature to %d", target_temp)
        await self._do_control_post(device_id, Tset=target_temp)
        cached_state.timestamp = int(time())
        cached_state.attrs["Tset"] = target_temp

    async def hydrojet_spa_set_locked(self, device_id: str, locked: bool) -> None:
        """Lock or unlock the physical control panel on a spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting lock state to %s", "ON" if locked else "OFF")
        await self._do_control_post(device_id, bit6=1 if locked else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["bit6"] = locked

    async def hydrojet_spa_set_bubbles(
        self, device_id: str, bubbles: HydrojetBubbles
    ) -> None:
        """Turn the bubbles on/off on an Airjet spa device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting bubbles mode to %d", bubbles)
        await self._do_control_post(device_id, wave=bubbles)
        cached_state.timestamp = int(time())
        cached_state.attrs["wave"] = bubbles
        if bubbles:
            cached_state.attrs["power"] = True

    async def pool_filter_set_power(self, device_id: str, power: bool) -> None:
        """Control power to a pump device."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting power to %s", "ON" if power else "OFF")
        await self._do_control_post(device_id, power=1 if power else 0)
        cached_state.timestamp = int(time())
        cached_state.attrs["power"] = power

    async def pool_filter_set_time(self, device_id: str, hours: int) -> None:
        """Set filter timeout for for pool devices."""
        if (cached_state := self._state_cache.get(device_id)) is None:
            raise BestwayException(f"Device '{device_id}' is not recognised")

        _LOGGER.debug("Setting filter timeout to %d hours", hours)
        await self._do_control_post(device_id, time=hours)
        cached_state.timestamp = int(time())
        cached_state.attrs["time"] = hours

    async def _do_get(self, url: str) -> dict[str, Any]:
        """Make an API call to the specified URL, returning the response as a JSON object."""
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        async with async_timeout.timeout(_TIMEOUT):
            response = await self._session.get(url, headers=headers)
            await _raise_for_status(response)

            # All API responses are encoded using JSON, however the headers often incorrectly
            # state 'text/html' as the content type.
            # We have to disable the check to avoid an exception.
            response_json: dict[str, Any] = await response.json(content_type=None)
            return response_json

    async def _do_control_post(
        self, device_id: str, **kwargs: int | str
    ) -> dict[str, Any]:
        return await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            {"attrs": kwargs},
        )

    async def _do_post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """Make an API call to the specified URL, returning the response as a JSON object."""
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        async with async_timeout.timeout(_TIMEOUT):
            response = await self._session.post(url, headers=headers, json=body)
            await _raise_for_status(response)

            # All API responses are encoded using JSON, however the headers often incorrectly
            # state 'text/html' as the content type.
            # We have to disable the check to avoid an exception.
            response_json: dict[str, Any] = await response.json(content_type=None)
            return response_json
