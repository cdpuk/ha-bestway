"""AWS IoT API client for V02 Bestway devices.

Backend: AWS IoT (smarthub-eu.bestwaycorp.com)
Apps: Bestway Smart Spa app
Devices: V02 models (Airjet V02, Hydrojet V02, etc)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import secrets
import string
from time import time
from typing import Any

from aiohttp import ClientSession

from ..const import Backend
from ..model import BestwayApiResults, BestwayDevice, BubblesLevel, RawSnapshot
from ..raw_state import RawStateApi
from ..translation import v01_attrs_from_shadow
from .encryption import encrypt_command_payload

_LOGGER = logging.getLogger(__name__)

# AWS IoT API Constants
DEFAULT_API_BASE = "https://smarthub-eu.bestwaycorp.com"  # EU endpoint
APP_ID = "AhFLL54HnChhrxcl9ZUJL6QNfolTIB"
APP_SECRET = "4ECvVs13enL5AiYSmscNjvlaisklQDz7vWPCCWXcEFjhWfTmLT"
TIMEOUT = 10

# Regional API endpoints (from ServiceConfig.java)
API_ENDPOINTS = {
    "EU": "https://smarthub-eu.bestwaycorp.com",
    "US": "https://smarthub-us.bestwaycorp.com",
    "CN": "https://smarthub.bestwaycorp.cn",  # Note: .cn domain!
    # "DEV": "http://bestway.dev.mxchip.com.cn",  # Dev/Test only
}


class AwsIotException(Exception):
    """Base exception for AWS IoT API operations."""


class AwsIotAuthException(AwsIotException):
    """Authentication error."""


class AwsIotApi(RawStateApi):
    """AWS IoT API client, implementing the BackendApi protocol.

    Device discovery goes via homes -> rooms -> devices; state fetching
    normalizes shadow fields onto the shared V01 vocabulary; control
    commands are AES-encrypted; and the token is refreshed on demand.
    """

    def __init__(
        self,
        session: ClientSession,
        visitor_id: str,
        token: str | None = None,
        location: str = "GB",
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        """Initialize the API client. Authenticates on first use if no token
        is supplied.
        """
        super().__init__()
        self._session = session
        self._visitor_id = visitor_id
        self._token = token
        self._location = location
        self._api_base = api_base

    @staticmethod
    def generate_visitor_id() -> str:
        """Generate a random 16-character hex visitor_id for a new account."""
        return secrets.token_hex(8)  # 16 hex chars

    @staticmethod
    async def authenticate(
        session: ClientSession,
        visitor_id: str,
        location: str = "GB",
        api_base: str = DEFAULT_API_BASE,
    ) -> str:
        """Authenticate a visitor and return the auth token.

        visitor_id may come from a QR binding or an existing account;
        location is a routing code like "GB" or "US". Raises
        AwsIotAuthException if authentication fails.
        """
        # Generate nonce (lowercase letters + digits, not hex)
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
        timestamp = str(int(time()))
        signature_data = f"{APP_ID}{APP_SECRET}{nonce}{timestamp}"
        sign = hashlib.md5(signature_data.encode()).hexdigest().upper()

        push_type = "fcm"

        payload = {
            "app_id": APP_ID,
            "brand": "",  # Required by the endpoint even though it's always empty
            "lan_code": "en",
            "location": location,
            "marketing_notification": 0,  # Required by the endpoint
            "push_type": push_type,
            "timezone": "GMT",
            "visitor_id": visitor_id,
            "registration_id": "",
        }

        if push_type == "fcm":
            client_id = (
                secrets.token_urlsafe(11)[:15].replace("-", "").replace("_", "").lower()
            )
            payload["client_id"] = client_id

        headers = {
            "pushtype": push_type,
            "appid": APP_ID,
            "nonce": nonce,
            "ts": timestamp,
            "accept-language": "en",
            "sign": sign,
            "Authorization": "token",
            "Host": "smarthub-eu.bestwaycorp.com",
            "Connection": "Keep-Alive",
            "User-Agent": "okhttp/4.9.0",
            "Content-Type": "application/json; charset=UTF-8",
        }

        url = f"{api_base}/api/enduser/visitor"

        _LOGGER.debug("Authenticating visitor %s", visitor_id[:12])
        _LOGGER.debug("Payload: %s", payload)
        _LOGGER.debug("Nonce in headers: %s", "nonce" in headers)
        _LOGGER.debug("Sign in headers: %s", "sign" in headers)
        _LOGGER.debug("All header keys: %s", list(headers.keys()))

        async with asyncio.timeout(TIMEOUT):
            async with session.post(
                url, headers=headers, json=payload, ssl=False
            ) as resp:
                data = await resp.json()
                _LOGGER.debug("Auth response: %s", data)
                _LOGGER.debug("Response status: %s", resp.status)
                token = data.get("data", {}).get("token")

                if not token:
                    _LOGGER.error("No token in response. Full response: %s", data)
                    raise AwsIotAuthException("No token in authentication response")

                return str(token)

    @staticmethod
    async def bind_qr_code(
        session: ClientSession,
        qr_code: str,
        visitor_id: str,
        token: str,
        api_base: str = DEFAULT_API_BASE,
    ) -> dict[str, Any] | None:
        """Bind a device to the visitor account using a QR code (must start
        with "RW_Share_"). Returns the device info dict, or None if the
        gateway didn't return one. Raises AwsIotException if the QR code is
        malformed or binding fails.
        """
        if not qr_code.startswith("RW_Share_"):
            raise AwsIotException("Invalid QR code format")

        # Generate signature
        nonce = secrets.token_hex(16)
        timestamp = str(int(time()))
        signature_data = f"{APP_ID}{APP_SECRET}{nonce}{timestamp}"
        sign = hashlib.md5(signature_data.encode()).hexdigest().upper()

        payload = {
            "vercode": qr_code,
            "push_type": "android",  # Required for grant_device API
        }

        headers = {
            "pushtype": "android",
            "appid": APP_ID,
            "nonce": nonce,
            "ts": timestamp,
            "sign": sign,
            "Authorization": f"token {token}",  # "token" prefix required!
            "Content-Type": "application/json; charset=UTF-8",
        }

        url = f"{api_base}/api/enduser/grant_device"

        async with asyncio.timeout(TIMEOUT):
            response = await session.post(url, headers=headers, json=payload, ssl=False)

            if response.status in (400, 401, 4001, 4002):
                raise AwsIotException("QR code invalid, expired, or already used")

            response.raise_for_status()
            data = await response.json()

            result = data.get("data")
            return dict(result) if result else None

    def _generate_auth_headers(self) -> dict[str, str]:
        """Generate a fresh signed headers dict for an API request."""
        # Generate nonce (lowercase letters + digits, not hex)
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
        timestamp = str(int(time()))
        signature = (
            hashlib.md5(f"{APP_ID}{APP_SECRET}{nonce}{timestamp}".encode())
            .hexdigest()
            .upper()
        )

        return {
            "pushtype": "fcm",
            "appid": APP_ID,
            "nonce": nonce,
            "ts": timestamp,
            "accept-language": "en",
            "sign": signature,
            # Auth scheme is the literal word "token", not "Bearer".
            "Authorization": f"token {self._token}",
            "Host": "smarthub-eu.bestwaycorp.com",
            "Connection": "Keep-Alive",
            "User-Agent": "okhttp/4.9.0",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _do_get(self, path: str) -> dict[str, Any]:
        """GET an authenticated endpoint and return the parsed JSON body.

        Raises AwsIotAuthException on HTTP 401 (token expired or invalid),
        AwsIotException on any other non-200 response.
        """
        url = f"{self._api_base}{path}"
        headers = self._generate_auth_headers()

        _LOGGER.debug("GET %s", path)

        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(url, headers=headers, ssl=False) as response:
                data = await response.json()

                if response.status in (400, 401):
                    raise AwsIotAuthException("Token expired or invalid")

                if response.status != 200:
                    raise AwsIotException(f"API error: {response.status}")

                return dict(data)

    async def _do_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST to an authenticated endpoint and return the parsed JSON body.

        Same error handling as `_do_get`.
        """
        url = f"{self._api_base}{path}"
        headers = self._generate_auth_headers()

        _LOGGER.debug("POST %s", path)

        async with asyncio.timeout(TIMEOUT):
            async with self._session.post(
                url, headers=headers, json=data, ssl=False
            ) as response:
                result = await response.json()

                _LOGGER.debug(
                    "POST %s response (status=%d): %s", path, response.status, result
                )

                if response.status in (400, 401):
                    raise AwsIotAuthException("Token expired or invalid")

                if response.status != 200:
                    raise AwsIotException(f"API error: {response.status}")

                return dict(result)

    async def refresh_bindings(self) -> None:
        """Discover and store all devices under the visitor account.

        Discovery flow:
        1. GET /api/enduser/homes -> list of homes
        2. For each home: GET /api/enduser/home/rooms?home_id=X -> rooms
        3. For each room: GET /api/enduser/home/room/devices?room_id=Y -> devices

        Cached after the first successful run - devices are only
        re-discovered if the device list is currently empty.
        """
        # Skip discovery if we already have devices (cache)
        if self.devices:
            _LOGGER.debug("Using cached device list (%d devices)", len(self.devices))
            return

        _LOGGER.debug("Discovering devices for visitor %s", self._visitor_id[:12])

        discovered_devices = []

        # Devices are nested three levels deep: homes -> rooms -> devices.
        homes_response = await self._do_get("/api/enduser/homes")
        _LOGGER.debug("Homes API response: %s", homes_response)

        # Check for API error code
        if homes_response.get("code") != 0:
            _LOGGER.error("Failed to get homes: %s", homes_response.get("message"))
            return

        homes = homes_response.get("data", {}).get("list", [])
        _LOGGER.debug("Found %d homes", len(homes))

        for home in homes:
            home_id = home.get("id")
            home_name = home.get("name", "Unknown")
            _LOGGER.debug("Processing home: %s (id=%s)", home_name, home_id)

            # Get rooms in this home
            rooms_response = await self._do_get(
                f"/api/enduser/home/rooms?home_id={home_id}"
            )

            # Check for API error
            if rooms_response.get("code") != 0:
                _LOGGER.warning("Failed to get rooms for home %s", home_id)
                continue

            rooms = rooms_response.get("data", {}).get("list", [])
            _LOGGER.debug("Found %d room(s) in home %s", len(rooms), home_name)

            for room in rooms:
                room_id = room.get("id")
                room_name = room.get("name", "Unknown")
                _LOGGER.debug("Processing room: %s (id=%s)", room_name, room_id)

                # Get devices in this room
                devices_response = await self._do_get(
                    f"/api/enduser/home/room/devices?room_id={room_id}"
                )

                # Check for API error
                if devices_response.get("code") != 0:
                    _LOGGER.warning("Failed to get devices for room %s", room_id)
                    continue

                devices = devices_response.get("data", {}).get("list", [])
                _LOGGER.debug("Found %d device(s) in room %s", len(devices), room_name)
                discovered_devices.extend(devices)

        _LOGGER.info("Discovered %d devices", len(discovered_devices))

        # Convert to BestwayDevice format
        self.devices = {}
        for dev in discovered_devices:
            device_id = dev["device_id"]
            product_id = dev.get("product_id", "UNKNOWN").strip()  # e.g., "T53NN8"
            product_series = (
                dev.get("product_series", "AIRJET").strip().replace(" ", "_")
            )  # Normalize spaces to underscores

            device = BestwayDevice(
                protocol_version=2,  # V02 protocol
                device_id=device_id,
                product_name=product_series,  # For backwards compat (V02 uses series as name)
                alias=dev.get("device_alias")
                or dev.get("device_name")
                or device_id[:12],
                mcu_soft_version=dev.get("mcu_version", "unknown"),
                mcu_hard_version=dev.get("mcu_version", "unknown"),
                wifi_soft_version=dev.get("wifi_version", "unknown"),
                wifi_hard_version=dev.get("wifi_version", "unknown"),
                is_online=dev.get("is_online", True),
                ws_host=dev.get(
                    "service_region", "eu-central-1"
                ),  # Store region in ws_host
                ws_port=443,  # AWS IoT WebSocket uses standard HTTPS port
                backend=Backend.AWS_IOT,
                product_id=product_id,  # Model ID, used when fetching the shadow
                product_series=product_series,  # Drives device_type
            )

            _LOGGER.info(
                "Device %s: product_id=%s, product_series=%s, device_type=%s",
                device.alias,
                product_id,
                product_series,
                device.device_type,
            )

            self.devices[device_id] = device

    async def fetch_data(self) -> BestwayApiResults:
        """Fetch latest state for all devices.

        For each device: POST /api/device/thing_shadow/ with device_id and
        product_id, parse shadow.state.reported/desired, and store the raw
        AWS field names (water_temperature, temperature_setting, etc.) in
        the state cache.
        """
        for device_id in self.devices:
            try:
                device = self.devices[device_id]

                payload = {
                    "device_id": device_id,
                    "product_id": device.product_id or device.product_name,
                }

                shadow_response = await self._do_post(
                    "/api/device/thing_shadow/", payload
                )

                raw_data = shadow_response.get("data", {})

                # Merge reported + desired so HA reflects the target state
                # (matches what the Bestway app shows) instead of lagging on
                # reported until the device fully acks.
                if "state" in raw_data and isinstance(raw_data["state"], dict):
                    reported = raw_data["state"].get("reported") or {}
                    desired = raw_data["state"].get("desired") or {}
                    if reported or desired:
                        device_state = {**reported, **desired}
                    else:
                        device_state = raw_data["state"]
                else:
                    device_state = raw_data

                _LOGGER.debug(
                    "Raw device_state for %s has %d fields: %s",
                    device_id[:12],
                    len(device_state),
                    list(device_state.keys()),
                )

                mapped = v01_attrs_from_shadow(device_state)

                _LOGGER.debug(
                    "After normalization: %d fields: %s",
                    len(mapped),
                    list(mapped.keys()),
                )

                # Update state cache
                self._raw_state[device_id] = RawSnapshot(
                    timestamp=int(time()), attrs=mapped
                )

                _LOGGER.debug(
                    "Fetched state for device %s: %d fields",
                    device_id[:12],
                    len(mapped),
                )

            except Exception as err:
                _LOGGER.warning(
                    "Failed to fetch state for device %s: %s", device_id[:12], err
                )
                # Keep existing cache or mark offline
                if device_id not in self._raw_state:
                    self._raw_state[device_id] = RawSnapshot(
                        timestamp=int(time()), attrs={}
                    )

        return self._results()

    async def set_device_state(
        self, device_id: str, state_updates: dict[str, Any]
    ) -> bool:
        """Write a shadow update for the given AWS field names and values
        (e.g. {"power_state": 1, "heater_state": 3}). Returns True if the
        gateway accepted the command.
        """
        # Command values are plain ints; unwrap bool/IntEnum to match.
        aws_updates = {}
        for key, value in state_updates.items():
            if isinstance(value, bool):
                value = 1 if value else 0
            elif hasattr(value, "value"):  # IntEnum
                value = int(value.value)
            elif not isinstance(value, int):
                value = int(value)
            aws_updates[key] = value

        if not aws_updates:
            return False

        headers = self._generate_auth_headers()
        sign = headers["sign"]

        _LOGGER.debug("Using sign for encryption: %s", sign[:16])

        # The shadow payload's "desired" field is a JSON string, not a
        # nested object.
        shadow_payload = {"state": {"desired": aws_updates}}
        desired_json_string = json.dumps(shadow_payload, separators=(",", ":"))

        device = self.devices[device_id]
        command_payload = {
            "device_id": device_id,
            "product_id": device.product_id,
            "desired": desired_json_string,
        }

        plaintext = json.dumps(command_payload, separators=(",", ":"))

        _LOGGER.info(
            "v2 command: fields=%s, product_id=%s", aws_updates, device.product_id
        )
        _LOGGER.debug("v2 plaintext: %s", plaintext)

        encrypted_payload = encrypt_command_payload(sign, APP_SECRET, plaintext)
        body = {"encrypted_data": encrypted_payload}

        # Reuse the same headers the plaintext was encrypted with: they
        # carry the "sign" value the encryption key is derived from, so
        # regenerating headers here would encrypt with one sign and send
        # another.
        try:
            async with self._session.post(
                f"{self._api_base}/api/v2/device/command",
                headers=headers,
                json=body,
                ssl=False,
            ) as response:
                result = await response.json()
                _LOGGER.debug(
                    "v2 POST response (status=%d): %s", response.status, result
                )

                if result.get("code") == 0:
                    _LOGGER.info("v2 API command sent to device %s", device_id[:12])
                    return True
                else:
                    _LOGGER.warning(
                        "v2 API returned error code %s, falling back to v1",
                        result.get("code"),
                    )

        except Exception as err:
            _LOGGER.warning("v2 API error (%s), falling back to v1", str(err))

        # v1 fallback: same payload shape, sent unencrypted.
        _LOGGER.info("v1 fallback: using AWS field names")

        device = self.devices[device_id]
        v1_payload = {
            "device_id": device_id,
            "product_id": device.product_id,
            "desired": {"state": {"desired": aws_updates}},
        }

        _LOGGER.debug("v1 payload: %s", v1_payload)

        try:
            v1_result: dict[str, Any] = await self._do_post(
                "/api/device/command/", v1_payload
            )

            if v1_result.get("code") == 0:
                _LOGGER.info("v1 API command sent to device %s", device_id[:12])
                return True
            else:
                _LOGGER.error("v1 API also failed with code %s", v1_result.get("code"))
                return False

        except Exception as err:
            _LOGGER.error(
                "Failed to send command to device %s: %s", device_id[:12], err
            )
            return False

    # AWS IoT has a single wire vocabulary, so each setter below is one
    # implementation with no device_type dispatch (contrast with Gizwits,
    # which has several).
    async def set_power(self, device_id: str, power: bool) -> None:
        """Set power state."""
        await self.set_device_state(device_id, {"power_state": 1 if power else 0})

    async def set_filter(self, device_id: str, filtering: bool) -> None:
        """Set filter state."""
        await self.set_device_state(device_id, {"filter_state": 1 if filtering else 0})

    async def set_heat(self, device_id: str, heat: bool) -> None:
        """Set heater state."""
        await self.set_device_state(device_id, {"heater_state": 1 if heat else 0})

    async def set_locked(self, device_id: str, locked: bool) -> None:
        """Set locked state."""
        await self.set_device_state(device_id, {"locked": 1 if locked else 0})

    async def set_jets(self, device_id: str, jets: bool) -> None:
        """Set jets state."""
        await self.set_device_state(device_id, {"hydrojet_state": 1 if jets else 0})

    async def set_target_temperature(self, device_id: str, temperature: int) -> None:
        """Set target temperature (device-native unit)."""
        await self.set_device_state(device_id, {"temperature_setting": temperature})

    async def set_bubbles(self, device_id: str, bubbles: BubblesLevel) -> None:
        """Set bubbles level.

        V02 reports absolute wave_state values: OFF=0, MEDIUM=40, MAX=100.
        Physical button cycles OFF -> MAX -> MEDIUM -> OFF.
        """
        value_map = {
            BubblesLevel.OFF: 0,
            BubblesLevel.MEDIUM: 40,  # V02 uses 40 not 50!
            BubblesLevel.MAX: 100,
        }
        target_value = value_map[bubbles]
        await self.set_device_state(device_id, {"wave_state": target_value})
        _LOGGER.debug("Set bubbles to %s (wave_state=%d)", bubbles.name, target_value)

    async def set_pool_timer(self, device_id: str, hours: int) -> None:
        """Not supported on V02 devices."""
        raise NotImplementedError("Pool filter not supported on V02 devices")
