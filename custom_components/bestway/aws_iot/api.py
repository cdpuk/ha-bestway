"""AWS IoT API client for V02 Bestway devices.

This module implements the AWS IoT backend API client that matches the Gizwits
BestwayApi interface, enabling seamless integration with the existing coordinator
and entity infrastructure.

Backend: AWS IoT (smarthub-eu.bestwaycorp.com)
Apps: Bestway Smart Spa app
Devices: V02 models (Airjet V02, Hydrojet V02, etc)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from time import time
from typing import Any

from aiohttp import ClientSession

from .encryption import encrypt_command_payload
from ..bestway.model import (
    AIRJET_V01_BUBBLES_MAP,
    BestwayDevice,
    BestwayDeviceStatus,
    BestwayDeviceType,
    BubblesLevel,
    HYDROJET_BUBBLES_MAP,
)
from ..const import BACKEND_AWS_IOT

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


class AwsIotApi:
    """AWS IoT API client matching Gizwits BestwayApi interface.

    This client provides the same interface as Gizwits BestwayApi, enabling
    drop-in replacement in the coordinator and entity infrastructure.

    Key responsibilities:
    - Device discovery via homes → rooms → devices
    - State fetching with field normalization
    - Control commands with encryption
    - Token refresh handling
    """

    def __init__(
        self,
        session: ClientSession,
        visitor_id: str,
        token: str | None = None,
        location: str = "GB",
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        """Initialize AWS IoT API client.

        Args:
            session: aiohttp ClientSession for HTTP requests
            visitor_id: Visitor ID from QR code or existing account
            token: Authentication token (optional, will authenticate if None)
            location: Location code (e.g., "GB", "US") for API routing
            api_base: API endpoint base URL (defaults to EU endpoint)
        """
        self._session = session
        self._visitor_id = visitor_id
        self._token = token
        self._location = location
        self._api_base = api_base

        # Device registry (matches Gizwits interface)
        self.devices: dict[str, BestwayDevice] = {}

        # State cache (matches Gizwits interface)
        self._state_cache: dict[str, BestwayDeviceStatus] = {}

    @staticmethod
    def generate_visitor_id() -> str:
        """Generate random visitor_id for new account.

        Returns:
            16-character hex visitor_id
        """
        return secrets.token_hex(8)  # 16 hex chars

    @staticmethod
    def normalize_aws_state(device_state: dict[str, Any]) -> dict[str, Any]:
        """Normalize AWS IoT field names to Gizwits V01 equivalents.

        This normalization allows existing V01 entities to work unchanged with V02 devices.
        Used by both fetch_data() and WebSocket message processing.

        Args:
            device_state: Raw state from AWS IoT device shadow

        Returns:
            Dict with normalized Gizwits V01 field names
        """
        warning = device_state.get("warning")
        error_code = device_state.get("error_code")
        power_state = device_state.get("power_state")
        filter_state = device_state.get("filter_state")
        temperature_unit = device_state.get("temperature_unit", 1)
        wave_state = device_state.get("wave_state", 0)

        # V02 wave_state actual values: 0=OFF, 40=MEDIUM, 100=HIGH
        # Map to V01 Airjet format (0/50/100) for AIRJET_V01_BUBBLES_MAP compatibility
        # Note: Hydrojet uses 40 for MEDIUM, so no mapping needed there
        if wave_state == 40:
            wave_normalized = 50  # Map V02 MEDIUM (40) → V01 Airjet MEDIUM (50)
        else:
            wave_normalized = wave_state  # 0 and 100 are same in both

        # Build normalized dict, only including fields with actual values
        # This prevents None values from overwriting existing data during merges
        normalized = {}

        # Version fields (diagnostic) - only if present
        if "wifivertion" in device_state:
            normalized["wifi_version"] = device_state["wifivertion"]
        if "otastatus" in device_state:
            normalized["ota_status"] = device_state["otastatus"]
        if "mcuversion" in device_state:
            normalized["mcu_version"] = device_state["mcuversion"]
        if "trdversion" in device_state:
            normalized["trd_version"] = device_state["trdversion"]
        if "ConnectType" in device_state:
            normalized["connect_type"] = device_state["ConnectType"]

        # Control state - use exact V01 field names!
        if power_state is not None:
            normalized["power"] = bool(power_state == 1)
        if device_state.get("heater_state") is not None:
            # Heater state values (same for V01 and V02):
            # 0 = OFF
            # 1 = ON (heater enabled, starting to heat)
            # 3 = HEATING (actively heating toward target)
            # 4 = TARGET_REACHED (at target temperature, maintaining)
            normalized["heat"] = device_state["heater_state"]
        if wave_state is not None:
            normalized["wave"] = wave_normalized
        if device_state.get("filter_state") is not None:
            normalized["filter"] = device_state["filter_state"]
        if device_state.get("hydrojet_state") is not None:
            normalized["jet"] = bool(device_state["hydrojet_state"] == 1)
        if device_state.get("locked") is not None:
            normalized["locked"] = device_state["locked"]

        # Temperature - use V01 field names (capital T!)
        if device_state.get("water_temperature") is not None:
            normalized["Tnow"] = device_state["water_temperature"]
        if device_state.get("temperature_setting") is not None:
            normalized["Tset"] = device_state["temperature_setting"]
        if "temperature_unit" in device_state:
            normalized["Tunit"] = temperature_unit

        # Errors - only include if present to avoid overwriting during delta merges
        if "warning" in device_state:
            normalized["warning"] = 0 if warning == "" else warning
        if "error_code" in device_state:
            normalized["error"] = 0 if error_code == "" else error_code

        # Status
        if device_state.get("is_online") is not None:
            normalized["is_online"] = device_state["is_online"]

        # V01-specific fields for compatibility
        normalized["word3"] = 0  # Target reached flag (unknown for V02)

        return normalized

    @staticmethod
    async def authenticate(
        session: ClientSession,
        visitor_id: str,
        location: str = "GB",
        api_base: str = DEFAULT_API_BASE,
    ) -> str:
        """Authenticate visitor and get token.

        EXACT copy of working implementation from New_bestway_spa/spa_api.py
        Do NOT modify without testing against real API!

        Args:
            session: aiohttp ClientSession
            visitor_id: Visitor ID from QR binding or existing account
            location: Location code (e.g., "GB", "US")
            api_base: API endpoint base URL (defaults to EU endpoint)

        Returns:
            Authentication token

        Raises:
            AwsIotAuthException: If authentication fails
        """
        import random
        import string

        # Generate nonce EXACTLY as reference (lowercase + digits, NOT hex!)
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
        timestamp = str(int(time()))
        signature_data = f"{APP_ID}{APP_SECRET}{nonce}{timestamp}"
        sign = hashlib.md5(signature_data.encode()).hexdigest().upper()

        push_type = "fcm"

        # Payload field order EXACTLY as reference
        payload = {
            "app_id": APP_ID,
            "brand": "",  # CRITICAL: Required by API
            "lan_code": "en",
            "location": location,
            "marketing_notification": 0,  # CRITICAL: Required by API
            "push_type": push_type,
            "timezone": "GMT",
            "visitor_id": visitor_id,
            "registration_id": "",
        }

        # Add client_id conditionally (reference logic)
        if push_type == "fcm":
            client_id = secrets.token_urlsafe(11)[:15].replace("-", "").replace("_", "").lower()
            payload["client_id"] = client_id

        # Headers EXACTLY as reference
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
        _LOGGER.debug("Nonce in headers: %s", 'nonce' in headers)
        _LOGGER.debug("Sign in headers: %s", 'sign' in headers)
        _LOGGER.debug("All header keys: %s", list(headers.keys()))

        async with asyncio.timeout(TIMEOUT):
            async with session.post(url, headers=headers, json=payload, ssl=False) as resp:
                data = await resp.json()
                _LOGGER.debug("Auth response: %s", data)
                _LOGGER.debug("Response status: %s", resp.status)
                token = data.get("data", {}).get("token")

                if not token:
                    _LOGGER.error("No token in response. Full response: %s", data)
                    raise AwsIotAuthException("No token in authentication response")

                return token

    @staticmethod
    async def bind_qr_code(
        session: ClientSession,
        qr_code: str,
        visitor_id: str,
        token: str,
        api_base: str = DEFAULT_API_BASE,
    ) -> dict[str, Any] | None:
        """Bind device to visitor account using QR code.

        Args:
            session: aiohttp ClientSession
            qr_code: QR code from spa (must start with "RW_Share_")
            visitor_id: Visitor ID for binding
            token: Authentication token
            api_base: API endpoint base URL (defaults to EU endpoint)

        Returns:
            Device info dict if successful, None otherwise

        Raises:
            AwsIotException: If binding fails
        """
        # Validate QR format
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

            return data.get("data")

    def _generate_auth_headers(self) -> dict[str, str]:
        """Generate authentication headers for API requests.

        EXACT copy of reference implementation.

        Returns:
            Headers dict with signature and authentication
        """
        import random
        import string

        # Generate nonce EXACTLY as reference
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=32))
        timestamp = str(int(time()))
        signature = hashlib.md5(f"{APP_ID}{APP_SECRET}{nonce}{timestamp}".encode()).hexdigest().upper()

        # Headers EXACTLY as reference (order matters!)
        return {
            "pushtype": "fcm",
            "appid": APP_ID,
            "nonce": nonce,
            "ts": timestamp,
            "accept-language": "en",
            "sign": signature,
            "Authorization": f"token {self._token}",  # "token" not "Bearer"!
            "Host": "smarthub-eu.bestwaycorp.com",
            "Connection": "Keep-Alive",
            "User-Agent": "okhttp/4.9.0",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _do_get(self, path: str) -> dict[str, Any]:
        """Execute GET request with authentication.

        Args:
            path: API endpoint path

        Returns:
            Response JSON data

        Raises:
            AwsIotAuthException: On HTTP 401 (invalid token)
            AwsIotException: On other errors
        """
        url = f"{self._api_base}{path}"
        headers = self._generate_auth_headers()

        _LOGGER.debug("GET %s", path)

        async with asyncio.timeout(TIMEOUT):
            async with self._session.get(url, headers=headers, ssl=False) as response:
                data = await response.json()

                # Check for errors
                if response.status in (400, 401):
                    raise AwsIotAuthException("Token expired or invalid")

                if response.status != 200:
                    raise AwsIotException(f"API error: {response.status}")

                return data

    async def _do_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """Execute POST request with authentication.

        Args:
            path: API endpoint path
            data: Request body data

        Returns:
            Response JSON data

        Raises:
            AwsIotAuthException: On HTTP 401 (invalid token)
            AwsIotException: On other errors
        """
        url = f"{self._api_base}{path}"
        headers = self._generate_auth_headers()

        _LOGGER.debug("POST %s", path)

        async with asyncio.timeout(TIMEOUT):
            async with self._session.post(url, headers=headers, json=data, ssl=False) as response:
                result = await response.json()

                _LOGGER.debug("POST %s response (status=%d): %s", path, response.status, result)

                # Check for errors
                if response.status in (400, 401):
                    raise AwsIotAuthException("Token expired or invalid")

                if response.status != 200:
                    raise AwsIotException(f"API error: {response.status}")

                return result

    async def refresh_bindings(self) -> None:
        """Discover and store all devices under visitor account.

        Implements the same interface as Gizwits BestwayApi.refresh_bindings().
        Populates self.devices with all discovered devices.

        Discovery flow:
        1. GET /api/enduser/homes → list of homes
        2. For each home: GET /api/enduser/home/rooms?home_id=X → rooms
        3. For each room: GET /api/enduser/home/room/devices?room_id=Y → devices
        4. Create BestwayDevice for each device with backend=BACKEND_AWS_IOT

        Note: Device discovery is cached after first successful run.
        Devices are only re-discovered if device list is empty.
        This reduces API load from N calls every 5min to N calls once per session.
        """
        # Skip discovery if we already have devices (cache)
        if self.devices:
            _LOGGER.debug("Using cached device list (%d devices)", len(self.devices))
            return

        _LOGGER.debug("Discovering devices for visitor %s", self._visitor_id[:12])

        discovered_devices = []

        # Step 1: Get homes
        homes_response = await self._do_get("/api/enduser/homes")
        _LOGGER.debug("Homes API response: %s", homes_response)

        # Check for API error code
        if homes_response.get("code") != 0:
            _LOGGER.error("Failed to get homes: %s", homes_response.get("message"))
            return

        homes = homes_response.get("data", {}).get("list", [])
        _LOGGER.debug("Found %d homes", len(homes))

        # Step 2 & 3: Get rooms and devices for each home
        for home in homes:
            home_id = home.get("id")  # EXACT reference field name
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
                room_id = room.get("id")  # EXACT reference field name
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
            product_series = dev.get("product_series", "AIRJET").strip().replace(" ", "_")  # Normalize spaces to underscores

            device = BestwayDevice(
                protocol_version=2,  # V02 protocol
                device_id=device_id,
                product_name=product_series,  # For backwards compat (V02 uses series as name)
                alias=dev.get("device_alias") or dev.get("device_name") or device_id[:12],
                mcu_soft_version=dev.get("mcu_version", "unknown"),
                mcu_hard_version=dev.get("mcu_version", "unknown"),
                wifi_soft_version=dev.get("wifi_version", "unknown"),
                wifi_hard_version=dev.get("wifi_version", "unknown"),
                is_online=dev.get("is_online", True),
                ws_host=dev.get("service_region", "eu-central-1"),  # Store region in ws_host
                ws_port=443,  # AWS IoT WebSocket uses standard HTTPS port
                backend=BACKEND_AWS_IOT,
                product_id=product_id,  # NEW: Model ID for shadow fetch
                product_series=product_series,  # NEW: Series for device_type
            )

            _LOGGER.info(
                "Device %s: product_id=%s, product_series=%s, device_type=%s",
                device.alias,
                product_id,
                product_series,
                device.device_type,
            )

            self.devices[device_id] = device

    async def fetch_data(self) -> Any:  # Returns BestwayApiResults
        """Fetch latest state for all devices.

        Implements the same interface as Gizwits BestwayApi.fetch_data().

        For each device:
        1. POST /api/device/thing_shadow/ with device_id + product_id
        2. Parse shadow.state.reported or shadow.state.desired
        3. Return raw AWS field names (water_temperature, temperature_setting, etc.)
        4. Store in state cache

        Returns:
            BestwayApiResults with devices dict
        """
        # Import here to avoid circular dependency
        from ..bestway.api import BestwayApiResults

        for device_id in self.devices:
            try:
                # Get device metadata
                device = self.devices[device_id]

                # Build payload with device_id and product_id (EXACT reference format)
                payload = {
                    "device_id": device_id,
                    "product_id": device.product_id or device.product_name,  # Model ID (e.g., "T53NN8")
                }

                # Fetch device shadow using POST (EXACT reference endpoint!)
                shadow_response = await self._do_post(
                    "/api/device/thing_shadow/",
                    payload
                )

                # Extract state (EXACT reference logic!)
                raw_data = shadow_response.get("data", {})

                # Try reported first, then desired, then raw state (reference logic)
                if "state" in raw_data:
                    if "reported" in raw_data["state"]:
                        device_state = raw_data["state"]["reported"]
                    elif "desired" in raw_data["state"]:
                        device_state = raw_data["state"]["desired"]
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

                # Normalize AWS field names to Gizwits V01 equivalents
                mapped = self.normalize_aws_state(device_state)

                _LOGGER.debug(
                    "After normalization: %d fields: %s",
                    len(mapped),
                    list(mapped.keys()),
                )

                # Update state cache
                self._state_cache[device_id] = BestwayDeviceStatus(
                    timestamp=int(time()), attrs=mapped
                )

                _LOGGER.debug(
                    "Fetched state for device %s: %d fields",
                    device_id[:12],
                    len(mapped),
                )

            except Exception as err:
                _LOGGER.warning("Failed to fetch state for device %s: %s", device_id[:12], err)
                # Keep existing cache or mark offline
                if device_id not in self._state_cache:
                    self._state_cache[device_id] = BestwayDeviceStatus(
                        timestamp=int(time()), attrs={}
                    )

        return BestwayApiResults(devices=self._state_cache)

    async def set_device_state(
        self, device_id: str, state_updates: dict[str, Any]
    ) -> bool:
        """Set device state fields using shadow update.

        Args:
            device_id: Target device ID
            state_updates: Dict of AWS field names and values
                         (e.g., "power_state", "heater_state", "temperature_setting")

        Returns:
            True if successful

        Example:
            await api.set_device_state("abc123", {"power_state": 1, "heater_state": 3})
        """
        # Convert bool/enum to int (commands use AWS field names!)
        aws_updates = {}
        for key, value in state_updates.items():
            if isinstance(value, bool):
                value = 1 if value else 0
            elif hasattr(value, 'value'):  # Extract from IntEnum
                value = int(value.value)
            elif not isinstance(value, int):
                value = int(value)
            aws_updates[key] = value

        if not aws_updates:
            return False

        # Get fresh signature for encryption
        import json as json_module

        headers = self._generate_auth_headers()
        sign = headers["sign"]

        _LOGGER.debug("Using sign for encryption: %s", sign[:16])

        # Build shadow payload using AWS field names (nested JSON string format!)
        shadow_payload = {"state": {"desired": aws_updates}}
        desired_json_string = json_module.dumps(shadow_payload, separators=(",", ":"))

        # Build command payload
        device = self.devices[device_id]
        command_payload = {
            "device_id": device_id,
            "product_id": device.product_id,  # Use exact product_id
            "desired": desired_json_string,  # JSON string!
        }

        # Serialize to JSON string
        plaintext = json_module.dumps(command_payload, separators=(",", ":"))

        _LOGGER.info("v2 command: fields=%s, product_id=%s", aws_updates, device.product_id)
        _LOGGER.debug("v2 plaintext: %s", plaintext)

        # Encrypt plaintext string (EXACT reference signature!)
        encrypted_payload = encrypt_command_payload(sign, APP_SECRET, plaintext)

        # Send command - use SAME headers that contain the sign we encrypted with!
        body = {"encrypted_data": encrypted_payload}

        # Try v2 API first (encrypted) - pass headers explicitly to ensure sign matches
        try:
            async with self._session.post(
                f"{self._api_base}/api/v2/device/command",
                headers=headers,  # Use SAME headers with matching sign!
                json=body,
                ssl=False
            ) as response:
                result = await response.json()
                _LOGGER.debug("v2 POST response (status=%d): %s", response.status, result)

                if result.get("code") == 0:
                    _LOGGER.info("✓ v2 API command sent to device %s", device_id[:12])
                    return True
                else:
                    _LOGGER.warning(
                        "v2 API returned error code %s, falling back to v1",
                        result.get("code"),
                    )

        except Exception as err:
            _LOGGER.warning("v2 API error (%s), falling back to v1", str(err))

        # v1 API fallback (unencrypted, reference implementation)
        _LOGGER.info("v1 fallback: using AWS field names")

        device = self.devices[device_id]
        v1_payload = {
            "device_id": device_id,
            "product_id": device.product_id,
            "desired": {"state": {"desired": aws_updates}},  # AWS field names!
        }

        _LOGGER.debug("v1 payload: %s", v1_payload)

        try:
            response = await self._do_post("/api/device/command/", v1_payload)

            if response.get("code") == 0:
                _LOGGER.info("✓ v1 API command sent to device %s", device_id[:12])
                return True
            else:
                _LOGGER.error("v1 API also failed with code %s", response.get("code"))
                return False

        except Exception as err:
            _LOGGER.error("Failed to send command to device %s: %s", device_id[:12], err)
            return False

    # Convenience methods matching Gizwits interface (with AWS field name translation)
    async def airjet_spa_set_power(self, device_id: str, state: bool) -> None:
        """Set power state for Airjet spa."""
        await self.set_device_state(device_id, {"power_state": 1 if state else 0})

    async def airjet_spa_set_filter(self, device_id: str, state: bool) -> None:
        """Set filter state for Airjet spa."""
        await self.set_device_state(device_id, {"filter_state": 1 if state else 0})

    async def airjet_spa_set_bubbles(self, device_id: str, state: bool) -> None:
        """Set bubbles state for Airjet spa."""
        await self.set_device_state(device_id, {"wave_state": 100 if state else 0})

    async def airjet_spa_set_locked(self, device_id: str, state: bool) -> None:
        """Set locked state for Airjet spa."""
        await self.set_device_state(device_id, {"locked": 1 if state else 0})

    async def airjet_spa_set_target_temp(
        self, device_id: str, temperature: int
    ) -> None:
        """Set target temperature for Airjet spa."""
        await self.set_device_state(device_id, {"temperature_setting": temperature})

    async def hydrojet_spa_set_power(self, device_id: str, state: bool) -> None:
        """Set power state for Hydrojet spa."""
        await self.set_device_state(device_id, {"power_state": 1 if state else 0})

    async def hydrojet_spa_set_filter(self, device_id: str, filter_state: int) -> None:
        """Set filter state for Hydrojet spa.

        V02 uses: 0=OFF, 1=ON (not 2!)
        """
        # Extract value from enum if needed
        value = filter_state.value if hasattr(filter_state, 'value') else filter_state
        # V02 uses 1 for ON, not 2
        if value == 2:
            value = 1
        await self.set_device_state(device_id, {"filter_state": value})

    async def hydrojet_spa_set_jets(self, device_id: str, state: bool) -> None:
        """Set jets state for Hydrojet spa."""
        await self.set_device_state(device_id, {"hydrojet_state": 1 if state else 0})

    async def hydrojet_spa_set_heat(self, device_id: str, heat_state: int) -> None:
        """Set heater state for Hydrojet spa.

        Climate entity sends: HydrojetHeat.OFF=0, HydrojetHeat.ON=3
        V02 command expects: heater_state=0 (OFF) or 1 (ON)
        Device will respond with: 0,1,3,4 based on heating progress
        """
        # Convert V01 enum value (0/3) to V02 command value (0/1)
        value = 1 if heat_state == 3 else 0
        await self.set_device_state(device_id, {"heater_state": value})

    async def hydrojet_spa_set_target_temp(
        self, device_id: str, temperature: int
    ) -> None:
        """Set target temperature for Hydrojet spa."""
        await self.set_device_state(device_id, {"temperature_setting": temperature})

    async def airjet_v01_spa_set_bubbles(
        self, device_id: str, level: BubblesLevel
    ) -> None:
        """Set bubbles level for Airjet spa.

        V02 device reports absolute values:
        - OFF: wave_state=0
        - MEDIUM: wave_state=40
        - HIGH: wave_state=100

        Physical button cycles: OFF → HIGH → MEDIUM → OFF
        Try sending absolute values first (simplest approach).
        """
        # Map BubblesLevel enum to V02 wave_state values
        value_map = {
            BubblesLevel.OFF: 0,
            BubblesLevel.MEDIUM: 40,  # V02 uses 40 not 50!
            BubblesLevel.MAX: 100,
        }

        target_value = value_map.get(level)
        if target_value is not None:
            await self.set_device_state(device_id, {"wave_state": target_value})
            _LOGGER.debug("Set bubbles to %s (wave_state=%d)", level.name, target_value)

    async def hydrojet_spa_set_bubbles(
        self, device_id: str, level: BubblesLevel
    ) -> None:
        """Set bubbles level for Hydrojet spa.

        V02 uses same toggle approach as Airjet V02.
        """
        # V02 uses toggle approach (same as Airjet V02)
        await self.airjet_v01_spa_set_bubbles(device_id, level)
