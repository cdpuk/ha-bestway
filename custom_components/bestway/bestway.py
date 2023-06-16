"""Bestway API."""
from dataclasses import dataclass
from enum import Enum, auto
import json
from logging import getLogger
from time import time

from typing import Any

from aiohttp import ClientResponse, ClientSession
import async_timeout

_LOGGER = getLogger(__name__)
_HEADERS = {
    "Content-type": "application/json; charset=UTF-8",
    "X-Gizwits-Application-Id": "98754e684ec045528b073876c34c7348",
}
_TIMEOUT = 10

# How old the latest update can be before a spa is considered offline
_CONNECTIVITY_TIMEOUT = 1000


class TemperatureUnit(Enum):
    """Temperature units supported by the spa."""

    CELSIUS = auto()
    FAHRENHEIT = auto()


@dataclass
class BestwayDevice:
    """A device under a user's account."""

    protocol_version: int
    device_id: str
    product_name: str
    alias: str
    mcu_soft_version: str
    mcu_hard_version: str
    wifi_soft_version: str
    is_online: bool


@dataclass
class BestwayDeviceStatus:
    """A snapshot of the status of a device."""

    timestamp: int
    temp_now: float
    temp_set: float
    temp_set_unit: TemperatureUnit
    heat_power: bool
    heat_temp_reach: bool
    filter_power: bool
    wave_power: bool
    locked: bool
    errors: list[int]
    earth_fault: bool

    @property
    def online(self) -> bool:
        """Determine whether the device is online based on the age of the latest update."""
        return self.timestamp > (time() - _CONNECTIVITY_TIMEOUT)


@dataclass
class BestwayUserToken:
    """User authentication token, obtained (and ideally stored) following a successful login."""

    user_id: str
    user_token: str
    expiry: int


@dataclass
class BestwayDeviceReport:
    """A device report, which combines device metadata with a current status snapshot."""

    device: BestwayDevice
    status: BestwayDeviceStatus | None


class BestwayException(Exception):
    """An exception returned via the API."""


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


async def raise_for_status(response: ClientResponse) -> None:
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
        self._bindings: dict[str, BestwayDevice] | None = None

        # Cache containing state information for each device received from the API
        # This is used to work around an annoyance where changes to settings via
        # a POST request are not immediately reflected in a subsequent GET request.
        #
        # When updating state via HA, we update the cache and return this value
        # until the API can provide us with a response containing a timestamp
        # more recent than the local update.
        self._local_state_cache: dict[str, BestwayDeviceStatus] = {}

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
            await raise_for_status(response)
            api_data = await response.json()

        return BestwayUserToken(
            api_data["uid"], api_data["token"], api_data["expire_at"]
        )

    async def refresh_bindings(self) -> None:
        """Refresh and store the list of devices available in the account."""
        self._bindings = {
            device.device_id: device for device in await self._get_bindings()
        }

    async def _get_bindings(self) -> list[BestwayDevice]:
        """Get the list of devices available in the account."""
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        api_data = await self._do_get(f"{self._api_root}/app/bindings", headers)
        return [
            BestwayDevice(
                raw["protoc"],
                raw["did"],
                raw["product_name"],
                raw["dev_alias"],
                raw["mcu_soft_version"],
                raw["mcu_hard_version"],
                raw["wifi_soft_version"],
                raw["is_online"],
            )
            for raw in api_data["devices"]
        ]

    async def fetch_data(self) -> dict[str, BestwayDeviceReport]:
        """Fetch the latest data for all devices."""

        results: dict[str, BestwayDeviceReport] = {}

        if not self._bindings:
            return results

        for did, device_info in self._bindings.items():
            latest_data = await self._do_get(
                f"{self._api_root}/app/devdata/{did}/latest", _HEADERS
            )

            # Get the age of the data according to the API
            api_update_timestamp = latest_data["updated_at"]

            # Zero indicates the device is offline
            # This has been observed after a device was offline for a few months
            if api_update_timestamp == 0:
                # In testing, the 'attrs' dictionary has been observed to be empty
                _LOGGER.debug("No data available for device %s", did)
                results[did] = BestwayDeviceReport(device_info, None)
                continue

            # Work out whether the received API update is more recent than the
            # locally cached state
            local_update_timestamp = 0
            if cached_state := self._local_state_cache.get(did):
                local_update_timestamp = cached_state.timestamp

            # If the API timestamp is more recent, update the cache
            if api_update_timestamp >= local_update_timestamp:
                _LOGGER.debug("New data received for device %s", did)
                device_attrs = latest_data["attr"]

                try:
                    errors = []
                    for err_num in range(1, 10):
                        if device_attrs[f"system_err{err_num}"] == 1:
                            errors.append(err_num)

                    device_status = BestwayDeviceStatus(
                        latest_data["updated_at"],
                        device_attrs["temp_now"],
                        device_attrs["temp_set"],
                        (
                            TemperatureUnit.CELSIUS
                            if device_attrs["temp_set_unit"] == "摄氏"
                            else TemperatureUnit.FAHRENHEIT
                        ),
                        device_attrs["heat_power"] == 1,
                        device_attrs["heat_temp_reach"] == 1,
                        device_attrs["filter_power"] == 1,
                        device_attrs["wave_power"] == 1,
                        device_attrs["locked"] == 1,
                        errors,
                        device_attrs["earth"] == 1,
                    )

                    self._local_state_cache[did] = device_status
                except KeyError as err:
                    _LOGGER.error(
                        "Unexpected missing key '%s' while decoding device attributes %s",
                        err,
                        json.dumps(device_attrs),
                    )
            else:
                _LOGGER.debug(
                    "Ignoring update for device %s as local data is newer", did
                )

            results[did] = BestwayDeviceReport(
                device_info,
                self._local_state_cache.get(did),
            )

        return results

    async def set_heat(self, device_id: str, heat: bool) -> None:
        """
        Turn the heater on/off.

        Turning the heater on will also turn on the filter pump.
        """
        _LOGGER.debug("Setting heater mode to %s", "ON" if heat else "OFF")
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            headers,
            {"attrs": {"heat_power": 1 if heat else 0}},
        )
        self._local_state_cache[device_id].timestamp = int(time())
        self._local_state_cache[device_id].heat_power = heat
        if heat:
            self._local_state_cache[device_id].filter_power = True

    async def set_filter(self, device_id: str, filtering: bool) -> None:
        """Turn the filter pump on/off."""
        _LOGGER.debug("Setting filter mode to %s", "ON" if filtering else "OFF")
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            headers,
            {"attrs": {"filter_power": 1 if filtering else 0}},
        )
        self._local_state_cache[device_id].timestamp = int(time())
        self._local_state_cache[device_id].filter_power = filtering
        if not filtering:
            self._local_state_cache[device_id].wave_power = False
            self._local_state_cache[device_id].heat_power = False

    async def set_locked(self, device_id: str, locked: bool) -> None:
        """Lock or unlock the physical control panel."""
        _LOGGER.debug("Setting lock state to %s", "ON" if locked else "OFF")
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            headers,
            {"attrs": {"locked": 1 if locked else 0}},
        )
        self._local_state_cache[device_id].timestamp = int(time())
        self._local_state_cache[device_id].locked = locked

    async def set_bubbles(self, device_id: str, bubbles: bool) -> None:
        """Turn the bubbles on/off."""
        _LOGGER.debug("Setting bubbles mode to %s", "ON" if bubbles else "OFF")
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            headers,
            {"attrs": {"wave_power": 1 if bubbles else 0}},
        )
        self._local_state_cache[device_id].timestamp = int(time())
        self._local_state_cache[device_id].filter_power = bubbles
        if bubbles:
            self._local_state_cache[device_id].filter_power = True

    async def set_target_temp(self, device_id: str, target_temp: int) -> None:
        """Set the target temperature."""
        _LOGGER.debug("Setting target temperature to %d", target_temp)
        headers = dict(_HEADERS)
        headers["X-Gizwits-User-token"] = self._user_token
        await self._do_post(
            f"{self._api_root}/app/control/{device_id}",
            headers,
            {"attrs": {"temp_set": target_temp}},
        )
        self._local_state_cache[device_id].timestamp = int(time())
        self._local_state_cache[device_id].temp_set = target_temp

    async def _do_get(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        """Make an API call to the specified URL, returning the response as a JSON object."""
        async with async_timeout.timeout(_TIMEOUT):
            response = await self._session.get(url, headers=headers)
            response.raise_for_status()

            # All API responses are encoded using JSON, however the headers often incorrectly
            # state 'text/html' as the content type.
            # We have to disable the check to avoid an exception.
            response_json: dict[str, Any] = await response.json(content_type=None)
            return response_json

    async def _do_post(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> dict[str, Any]:
        """Make an API call to the specified URL, returning the response as a JSON object."""
        async with async_timeout.timeout(_TIMEOUT):
            response = await self._session.post(url, headers=headers, json=body)
            await raise_for_status(response)

            # All API responses are encoded using JSON, however the headers often incorrectly
            # state 'text/html' as the content type.
            # We have to disable the check to avoid an exception.
            response_json: dict[str, Any] = await response.json(content_type=None)
            return response_json
