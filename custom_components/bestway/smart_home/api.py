"""Smart Home (Gizwits AEP) API client for newer "Bestway Connect" devices.

Backend: Gizwits AEP super-app gateway (smart-spa-*-app.bestwaycorp.com)
App: Bestway Connect (2025+), user-agent ``gizwitssuperapprn/*``
Devices: 2025+ UltraFit models (Airjet/Hydrojet V02) whose "Share device" QR
now yields a URL instead of an ``RW_Share_`` code (issue #135).

This client mirrors the ``AwsIotApi`` interface so it drops straight into the
existing coordinator and entity infrastructure. The device shadow exposes the
same field names the AWS IoT backend already handles, so state normalisation
is shared via :meth:`AwsIotApi.normalize_aws_state`.

Notes on the protocol (established by observing the official app):

* Auth is an anonymous session token; no username/password is required.
* Requests authenticate with ``X-Gizwits-Application-Id`` plus the session
  token in ``Authorization`` (and ``X-Gizwits-User-Token``). The app also
  sends an ``X-Gizwits-Ca-Signature`` (HmacSHA256) header, but the gateway
  does not enforce it on these endpoints, so we do not compute one.
* Every response is HTTP 200 with a business ``code`` in the JSON body
  (``"200"`` on success); errors are reported there, not via HTTP status.
"""

from __future__ import annotations

import asyncio
from logging import getLogger
import re
from time import time
from typing import Any
from urllib.parse import parse_qs, urlparse
import uuid

from aiohttp import ClientError, ClientSession

from ..bestway.model import BestwayDevice, BestwayDeviceStatus, BubblesLevel
from ..const import BACKEND_SMART_HOME

_LOGGER = getLogger(__name__)

# Gizwits AEP application id for the Bestway Connect app. Shared across
# regions (matches the AWS IoT backend, which also uses one id for EU/US).
APP_ID = "39ef26ff404a4cb1b5652f336d4bc045"
TIMEOUT = 15

# Regional gateway endpoints. The share URL host encodes the region as
# ``smart-spa-<region>-app``; the config flow region select is the fallback
# when only a bare share id is supplied.
API_ENDPOINTS = {
    "EU": "https://smart-spa-eu-app.bestwaycorp.com",
    "US": "https://smart-spa-us-app.bestwaycorp.com",
}
DEFAULT_API_BASE = API_ENDPOINTS["EU"]

# Host pattern for the new share URLs, e.g.
# https://smart-spa-eu-app.bestwaycorp.com/app/<appid>/shareDevice/index.html?shareId=<id>
_SHARE_HOST_RE = re.compile(
    r"^smart-spa-(?P<region>[a-z]{2})-app\.bestwaycorp\.com$", re.IGNORECASE
)
# A share id is a hex token. Kept deliberately broad (16-64 hex chars) so minor
# backend changes to the id length don't reject an otherwise valid invitation.
_SHARE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")

# Map known product keys to a product series so the existing device-type
# machinery (and therefore the right entities) applies. Unknown keys fall back
# to a generic Airjet V02, whose normalised fields cover the common controls.
_PRODUCT_KEY_SERIES = {
    "FTEW0E": "ULTRAFIT_AIRJET",
}


class SmartHomeException(Exception):
    """Base exception for Smart Home (AEP) API operations."""


class SmartHomeAuthException(SmartHomeException):
    """Authentication/session error."""


class SmartHomeShareException(SmartHomeException):
    """A device share invitation could not be redeemed."""


def parse_share_input(raw: str) -> tuple[str, str | None]:
    """Extract the share id (and region, if present) from user input.

    Accepts either the full share URL from the app's "Share device" QR code,
    or a bare share id. Returns ``(share_id, region_or_none)``.

    Raises:
        SmartHomeShareException: If no valid share id can be found. The message
            is safe to surface; it never includes the share id itself.
    """
    value = (raw or "").strip()
    if not value:
        raise SmartHomeShareException("missing_share_id")

    # Bare share id (not a URL).
    if "://" not in value and "/" not in value:
        if _SHARE_ID_RE.match(value):
            return value, None
        raise SmartHomeShareException("invalid_share_id")

    parsed = urlparse(value)
    host_match = _SHARE_HOST_RE.match(parsed.hostname or "")
    region = host_match.group("region").upper() if host_match else None

    share_id = parse_qs(parsed.query).get("shareId", [""])[0].strip()
    if not share_id:
        raise SmartHomeShareException("missing_share_id")
    if not _SHARE_ID_RE.match(share_id):
        raise SmartHomeShareException("invalid_share_id")

    return share_id, (region if region in API_ENDPOINTS else None)


class SmartHomeApi:
    """Smart Home (AEP) API client matching the AwsIotApi interface."""

    def __init__(
        self,
        session: ClientSession,
        phone_id: str,
        token: str | None = None,
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        """Initialise the client.

        Args:
            session: aiohttp ClientSession for HTTP requests.
            phone_id: Stable per-install id used for the anonymous session.
            token: Session token (optional; re-authenticate if None).
            api_base: Regional gateway base URL.
        """
        self._session = session
        self._phone_id = phone_id
        self._token = token
        self._api_base = api_base

        # Matches the AwsIotApi/BestwayApi interface consumed by the coordinator.
        self.devices: dict[str, BestwayDevice] = {}
        self._state_cache: dict[str, BestwayDeviceStatus] = {}

    @staticmethod
    def generate_phone_id() -> str:
        """Generate a stable per-install id for the anonymous session."""
        return str(uuid.uuid4())

    # ---- HTTP helpers -----------------------------------------------------

    def _headers(self, authed: bool = True) -> dict[str, str]:
        """Build request headers.

        The gateway does not enforce the HmacSHA256 signature the app sends,
        so only the application id and (when authed) the session token are
        required.
        """
        headers = {
            "X-Gizwits-Application-Id": APP_ID,
            "Content-Type": "application/json",
            "Accept": "application/json; charset=utf-8",
            "version": "1.0",
            "User-Agent": "gizwitssuperapprn/131600000",
        }
        if authed:
            if not self._token:
                raise SmartHomeAuthException("No session token available")
            headers["Authorization"] = self._token
            headers["X-Gizwits-User-Token"] = self._token
        return headers

    @staticmethod
    def _payload(data: Any) -> dict[str, Any]:
        """Wrap a data object in the gateway's standard request envelope."""
        return {"appKey": APP_ID, "data": data, "version": "1.0"}

    @staticmethod
    def _check(body: dict[str, Any]) -> dict[str, Any]:
        """Validate the business ``code`` inside an HTTP 200 response.

        The gateway returns errors in the body, not the HTTP status, so a plain
        ``raise_for_status`` is not enough (see issue #135).
        """
        code = str(body.get("code"))
        if body.get("error") or code != "200":
            # Map the auth/session codes to an auth exception so Home Assistant
            # can trigger re-authentication rather than a generic failure.
            if code in ("505", "401", "403"):
                raise SmartHomeAuthException(f"Session rejected (code {code})")
            raise SmartHomeException(f"API error (code {code})")
        return body

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        authed: bool = True,
    ) -> dict[str, Any]:
        """Perform a request and return the validated JSON body."""
        url = f"{self._api_base}{path}"
        # Only attach a JSON body when there is one; passing json=None would
        # send the literal "null" instead of an empty body, which the share
        # redeem endpoint (empty body) rejects.
        kwargs: dict[str, Any] = {
            "headers": self._headers(authed=authed),
            "ssl": False,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.request(method, url, **kwargs) as response:
                    body = await response.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise SmartHomeException(f"Cannot reach Bestway API: {err}") from err
        if not isinstance(body, dict):
            raise SmartHomeException("Unexpected API response")
        return self._check(body)

    # ---- Authentication ---------------------------------------------------

    @staticmethod
    async def authenticate(
        session: ClientSession,
        phone_id: str,
        api_base: str = DEFAULT_API_BASE,
    ) -> str:
        """Create/refresh an anonymous session and return its token."""
        payload = {
            "appKey": APP_ID,
            "data": {"phoneId": phone_id, "homeName": "Home Assistant", "lang": "en"},
            "version": "1.0",
        }
        client = SmartHomeApi(session, phone_id, api_base=api_base)
        body = await client._request(
            "POST", "/app/smart_home/login/anonymous", json_body=payload, authed=False
        )
        token = (body.get("data") or {}).get("userToken")
        if not token:
            raise SmartHomeAuthException("No token in login response")
        return str(token)

    # ---- Device sharing ---------------------------------------------------

    @staticmethod
    async def accept_share(
        session: ClientSession,
        share_id: str,
        token: str,
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        """Redeem a device-share invitation for the current session.

        The share id travels in the URL path with an empty request body.
        """
        client = SmartHomeApi(session, "", token=token, api_base=api_base)
        try:
            await client._request(
                "POST", f"/app/smartHome/homes/singleDeviceShareV2/{share_id}"
            )
        except SmartHomeException as err:
            # Re-raise with a translation key the config flow can show. The
            # share id is never included in the message.
            code = _extract_code(err)
            if code == "2000066":
                # "You have already shared this device" — the owner scanned
                # their own invitation. Treat as already-linked, not fatal.
                raise SmartHomeShareException("share_already_used") from err
            if code in ("4000002", "4000001"):
                raise SmartHomeShareException("invalid_share_id") from err
            if code in ("2000001", "2000021"):
                raise SmartHomeShareException("device_not_found") from err
            raise SmartHomeShareException("share_failed") from err

    # ---- Discovery + state ------------------------------------------------

    async def refresh_bindings(self) -> None:
        """Discover devices for the current session (cached after first run)."""
        if self.devices:
            _LOGGER.debug("Using cached device list (%d devices)", len(self.devices))
            return

        body = await self._request("GET", "/app/smartHome/v2/users/devices")
        raw_devices = body.get("data") or []
        _LOGGER.debug("Discovered %d device(s)", len(raw_devices))

        devices: dict[str, BestwayDevice] = {}
        for dev in raw_devices:
            mac = dev.get("mac")
            product_key = (dev.get("productKey") or "").strip()
            if not mac or not product_key:
                continue
            series = _PRODUCT_KEY_SERIES.get(product_key, "AIRJET")
            devices[mac] = BestwayDevice(
                protocol_version=2,
                device_id=mac,
                product_name=series,
                alias=dev.get("name") or mac,
                mcu_soft_version="unknown",
                mcu_hard_version="unknown",
                wifi_soft_version="unknown",
                wifi_hard_version="unknown",
                is_online=dev.get("onlineStatus") == 1,
                backend=BACKEND_SMART_HOME,
                product_id=product_key,
                product_series=series,
            )
        self.devices = devices

    async def fetch_data(self) -> Any:  # Returns BestwayApiResults
        """Fetch and normalise the latest state for all devices."""
        from ..aws_iot.api import AwsIotApi
        from ..bestway.api import BestwayApiResults

        for device_id, device in self.devices.items():
            try:
                body = await self._request(
                    "GET",
                    f"/app/device/shadow/{device.product_id}/{device_id}",
                )
                device_state = body.get("data") or {}
                mapped = AwsIotApi.normalize_aws_state(device_state)
                self._state_cache[device_id] = BestwayDeviceStatus(
                    timestamp=int(time()), attrs=mapped
                )
            except SmartHomeAuthException:
                # Let the coordinator surface auth failures for re-auth.
                raise
            except SmartHomeException as err:
                _LOGGER.warning("Failed to fetch state for a device: %s", err)
                if device_id not in self._state_cache:
                    self._state_cache[device_id] = BestwayDeviceStatus(
                        timestamp=int(time()), attrs={}
                    )

        return BestwayApiResults(devices=self._state_cache)

    async def set_device_state(
        self, device_id: str, state_updates: dict[str, Any]
    ) -> bool:
        """Send a control command using AWS-style field names (plaintext JSON)."""
        import json as json_module

        updates: dict[str, Any] = {}
        for key, value in state_updates.items():
            if isinstance(value, bool):
                value = 1 if value else 0
            elif hasattr(value, "value"):  # IntEnum
                value = int(value.value)
            elif not isinstance(value, int):
                value = int(value)
            updates[key] = value

        if not updates:
            return False

        device = self.devices[device_id]
        # The gateway expects `data` as a JSON *string* of the desired fields.
        payload = self._payload(json_module.dumps(updates, separators=(",", ":")))
        _LOGGER.debug("Smart Home command: fields=%s", list(updates.keys()))
        body = await self._request(
            "POST",
            f"/app/device/control/{device.product_id}/{device_id}",
            json_body=payload,
        )
        return bool(body.get("data"))

    # ---- Convenience methods (match AwsIotApi interface) ------------------
    #
    # These UltraFit devices report/accept a simple wave_state on/off (0/1)
    # rather than the 0/40/100 the AWS IoT backend uses, so the bubble helpers
    # are overridden accordingly. All other helpers reuse AWS field names.

    async def airjet_spa_set_power(self, device_id: str, state: bool) -> None:
        """Set power state."""
        await self.set_device_state(device_id, {"power_state": 1 if state else 0})

    async def airjet_spa_set_filter(self, device_id: str, state: bool) -> None:
        """Set filter state."""
        await self.set_device_state(device_id, {"filter_state": 1 if state else 0})

    async def airjet_spa_set_bubbles(self, device_id: str, state: bool) -> None:
        """Set bubbles on/off."""
        await self.set_device_state(device_id, {"wave_state": 1 if state else 0})

    async def airjet_spa_set_heat(self, device_id: str, heat: bool) -> None:
        """Set heater state."""
        await self.set_device_state(device_id, {"heater_state": 1 if heat else 0})

    async def airjet_spa_set_locked(self, device_id: str, state: bool) -> None:
        """Set panel lock state."""
        await self.set_device_state(device_id, {"locked": 1 if state else 0})

    async def airjet_spa_set_target_temp(
        self, device_id: str, temperature: int
    ) -> None:
        """Set target temperature."""
        await self.set_device_state(device_id, {"temperature_setting": temperature})

    async def hydrojet_spa_set_power(self, device_id: str, state: bool) -> None:
        """Set power state."""
        await self.set_device_state(device_id, {"power_state": 1 if state else 0})

    async def hydrojet_spa_set_filter(self, device_id: str, filter_state: int) -> None:
        """Set filter state (V02 uses 1 for ON, not 2)."""
        value = filter_state.value if hasattr(filter_state, "value") else filter_state
        if value == 2:
            value = 1
        await self.set_device_state(device_id, {"filter_state": value})

    async def hydrojet_spa_set_jets(self, device_id: str, state: bool) -> None:
        """Set jets state."""
        await self.set_device_state(device_id, {"hydrojet_state": 1 if state else 0})

    async def hydrojet_spa_set_heat(self, device_id: str, heat_state: int) -> None:
        """Set heater state (climate sends 0/3; device expects 0/1)."""
        value = 1 if heat_state == 3 else 0
        await self.set_device_state(device_id, {"heater_state": value})

    async def hydrojet_spa_set_target_temp(
        self, device_id: str, temperature: int
    ) -> None:
        """Set target temperature."""
        await self.set_device_state(device_id, {"temperature_setting": temperature})

    async def airjet_v01_spa_set_bubbles(
        self, device_id: str, level: BubblesLevel
    ) -> None:
        """Set bubbles from a 3-way level.

        UltraFit hardware observed so far is on/off only, so any non-OFF level
        maps to on. The precise level behaviour is verified against real
        hardware; users with on/off hardware can pick "On / Off only" in the
        integration options for a plain switch.
        """
        await self.set_device_state(
            device_id, {"wave_state": 0 if level == BubblesLevel.OFF else 1}
        )

    async def hydrojet_spa_set_bubbles(
        self, device_id: str, level: BubblesLevel
    ) -> None:
        """Set bubbles from a 3-way level (see airjet_v01_spa_set_bubbles)."""
        await self.airjet_v01_spa_set_bubbles(device_id, level)

    async def pool_filter_set_power(self, device_id: str, power: bool) -> None:
        """Not supported on these devices."""
        raise NotImplementedError("Pool filter not supported on Smart Home devices")

    async def pool_filter_set_time(self, device_id: str, hours: int) -> None:
        """Not supported on these devices."""
        raise NotImplementedError("Pool filter not supported on Smart Home devices")


def _extract_code(err: Exception) -> str | None:
    """Pull the numeric business code out of a SmartHomeException message."""
    match = re.search(r"code (\d+)", str(err))
    return match.group(1) if match else None
