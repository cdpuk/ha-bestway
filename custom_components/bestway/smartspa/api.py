"""SmartSpa gateway API client for post-July-2026 Bestway Connect devices.

After the Bestway Connect app update of ~23-24 July 2026, V02 devices moved to
a third backend (smart-spa-{eu,us,cn}-app.bestwaycorp.com, a React Native
"gizwitssuperapprn" gateway). The old share-QR flow became a targeted "home"
invitation that anonymous visitor accounts cannot redeem (issue #135), but the
new gateway supports plain account login, which sidesteps the QR flow entirely.

Protocol as reverse-engineered and verified end-to-end against live spas in
https://github.com/cdpuk/ha-bestway/issues/135 (Aug 2026):

* Login:   POST app/smart_home/login/pwd
           body is an ENVELOPE: {"appKey": <appid>, "data": {...}, "version": "1.0"}
           -> data.userToken
* Devices: GET  app/smart_home/users/devices          (auth header only)
* State:   GET  app/device/shadow/{productKey}/{mac}  (mac lowercase)
* Control: POST app/device/control/{productKey}/{mac}
           body: {"appKey": <appid>, "data": "<JSON STRING>", "version": "1.0"}

CRITICAL quirks (all confirmed on live hardware, EU + US):

1. The control "data" field must be a JSON *string* (json.dumps of the
   datapoints). Sending an {"attrs": {...}} object returns HTTP 200 /
   code "200" / data:true and SILENTLY DOES NOTHING. A 200 is not proof
   a write landed.
2. Writes use 1/0, but filter_state and heater_state READ BACK as 2 while
   running. Never compare a read against the value you wrote.
3. Writes take effect in ~5-10 s, not instantly.
4. While wave_state (bubbles) is 1, the shadow reports filter_state: 0 even
   if you write filter_state:1 in the same request; it returns to 2 when
   bubbles stop. Do not infer a filter failure from a read taken during a
   bubbles cycle.
5. Auth: only Content-MD5 (base64 of md5 of the body) + X-Gizwits-Application-Id
   + Authorization: <userToken>. No HMAC signature needed on this path.
6. Responses are {"code": "200", "message": ..., "data": ..., "error": bool}
   with code as a STRING. code "505" (message in Chinese) means "not logged
   in" -> re-authenticate and retry once.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from time import time
from typing import Any

from aiohttp import ClientSession

from ..aws_iot.api import AwsIotApi  # reuse normalize_aws_state (same field names)
from ..bestway.model import BubblesLevel
from ..bestway.translation import status_from_attrs
from ..const import Backend
from ..model import BestwayApiResults, BestwayDevice, BestwayDeviceType, RawSnapshot

_LOGGER = logging.getLogger(__name__)

# Application id of the new React Native app, valid only on Bestway's own
# gateway (Gizwits itself rejects it with 9003 "appid invalid").
SMARTSPA_APP_ID = "39ef26ff404a4cb1b5652f336d4bc045"

SMARTSPA_ENDPOINTS = {
    "EU": "https://smart-spa-eu-app.bestwaycorp.com",
    "US": "https://smart-spa-us-app.bestwaycorp.com",
    "CN": "https://smart-spa-cn-app.bestwaycorp.com",
}

TIMEOUT = 20  # the gateway can be slow; 10s caused spurious failures upstream


class SmartSpaException(Exception):
    """Base exception for SmartSpa API operations."""


class SmartSpaAuthException(SmartSpaException):
    """Authentication error (bad credentials or expired token)."""


def _content_md5(body: str) -> str:
    """base64(md5(body)) as required by the gateway on bodied requests."""
    return base64.b64encode(hashlib.md5(body.encode()).digest()).decode()


def _envelope(data: Any) -> dict[str, Any]:
    """Standard request envelope used by login and most POST endpoints."""
    return {"appKey": SMARTSPA_APP_ID, "data": data, "version": "1.0"}


class SmartSpaApi:
    """SmartSpa gateway client matching the BestwayApi/AwsIotApi interface.

    Drop-in for the coordinator and entity layer: exposes .devices,
    refresh_bindings(), fetch_data(), handle_partial_update(),
    set_device_state() and the semantic setters (set_power, set_filter, ...).
    """

    def __init__(
        self,
        session: ClientSession,
        account: str,
        password: str,
        api_base: str,
        token: str | None = None,
    ) -> None:
        """Initialize the client. Credentials are kept for re-login."""
        self._session = session
        self._account = account
        self._password = password
        self._api_base = api_base.rstrip("/")
        self._token = token

        # Interface expected by coordinator/entities
        self.devices: dict[str, BestwayDevice] = {}
        # Merge substrate for polled + WebSocket-delta state, prior to
        # translation into the typed DeviceStatus entities read.
        self._raw_state: dict[str, RawSnapshot] = {}

        # device_id -> (productKey, mac) for URL building
        self._routing: dict[str, tuple[str, str]] = {}

    def _results(self) -> BestwayApiResults:
        """Translate the raw state cache into typed results.

        A raw entry with no matching device translates against UNKNOWN
        rather than being dropped, so it still surfaces as a status with
        raw attrs even though no entity can be attached to it yet.
        """
        return BestwayApiResults(
            devices={
                device_id: status_from_attrs(
                    self.devices[device_id].device_type
                    if device_id in self.devices
                    else BestwayDeviceType.UNKNOWN,
                    snapshot.timestamp,
                    snapshot.attrs,
                )
                for device_id, snapshot in self._raw_state.items()
            }
        )

    def handle_partial_update(
        self, device_id: str, attrs: dict[str, Any]
    ) -> BestwayApiResults:
        """Merge a partial state delta and return freshly translated results.

        This backend has no WebSocket today, but implements the same
        interface as the other two for uniformity.
        """
        existing = self._raw_state.get(device_id)
        merged = {**existing.attrs, **attrs} if existing else dict(attrs)
        self._raw_state[device_id] = RawSnapshot(int(time()), merged)
        return self._results()

    # ------------------------------------------------------------------ auth

    @staticmethod
    async def authenticate(
        session: ClientSession, account: str, password: str, api_base: str
    ) -> str:
        """Log in with account credentials and return the userToken."""
        body_obj = _envelope(
            {
                "account": account,
                "password": password,
                "lang": "en",
                "refreshToken": True,
            }
        )
        body = json.dumps(body_obj, separators=(",", ":"))
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json; charset=utf-8",
            "Version": "1.0",
            "date": "null",
            "X-Gizwits-Application-Id": SMARTSPA_APP_ID,
            "Content-MD5": _content_md5(body),
        }
        url = f"{api_base.rstrip('/')}/app/smart_home/login/pwd"

        async with asyncio.timeout(TIMEOUT):
            async with session.post(url, data=body.encode(), headers=headers) as resp:
                result = await resp.json(content_type=None)

        code = str(result.get("code", ""))
        if code != "200" or not isinstance(result.get("data"), dict):
            # Don't log the password; the message is safe/useful.
            raise SmartSpaAuthException(
                f"Login failed (code {code}): {result.get('message')}"
            )

        token = result["data"].get("userToken")
        if not token:
            raise SmartSpaAuthException(
                f"Login succeeded but no userToken in response: {list(result['data'].keys())}"
            )
        _LOGGER.debug("SmartSpa login OK for %s", account)
        return str(token)

    async def _ensure_token(self) -> None:
        if not self._token:
            self._token = await self.authenticate(
                self._session, self._account, self._password, self._api_base
            )

    # -------------------------------------------------------------- requests

    def _headers(self, body: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json; charset=utf-8",
            "Version": "1.0",
            "date": "null",
            "X-Gizwits-Application-Id": SMARTSPA_APP_ID,
        }
        if body is not None:
            headers["Content-MD5"] = _content_md5(body)
        if self._token:
            # Bare token, NOT "Bearer <token>"; and it must go in Authorization,
            # not x-gizwits-user-token (that returns code 505).
            headers["Authorization"] = self._token
        return headers

    async def _request(
        self, method: str, path: str, body_obj: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a request; transparently re-login once on an expired token."""
        await self._ensure_token()

        body = (
            json.dumps(body_obj, separators=(",", ":"))
            if body_obj is not None
            else None
        )
        url = f"{self._api_base}/{path.lstrip('/')}"

        for attempt in (1, 2):
            async with asyncio.timeout(TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    data=body.encode() if body is not None else None,
                    headers=self._headers(body),
                ) as resp:
                    if resp.status == 401:
                        result: dict[str, Any] = {"code": "505"}
                    else:
                        result = await resp.json(content_type=None)

            code = str(result.get("code", ""))
            if code == "200":
                return result

            # 505 = not logged in / token invalidated server-side
            if code == "505" and attempt == 1:
                _LOGGER.info("SmartSpa token rejected, re-authenticating")
                self._token = None
                await self._ensure_token()
                continue

            raise SmartSpaException(
                f"{method} {path} failed (code {code}): {result.get('message')}"
            )

        raise SmartSpaAuthException("Re-authentication did not yield a valid session")

    # ------------------------------------------------------------- discovery

    @staticmethod
    def _first(d: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in d and d[key] not in (None, ""):
                return d[key]
        return None

    @staticmethod
    def _series_from_name(name: str) -> str:
        """Heuristic product_series so existing entity setup picks the right set."""
        lowered = name.lower()
        if "hydrojet" in lowered and "pro" in lowered:
            return "HYDROJET_PRO"
        if "hydrojet" in lowered:
            return "HYDROJET"
        if "ultrafit" in lowered:
            return "ULTRAFIT_AIRJET"
        return "AIRJET"

    async def refresh_bindings(self) -> None:
        """Discover devices on the account (cached after first success)."""
        if self.devices:
            return

        result = await self._request("GET", "app/smart_home/users/devices")
        data = result.get("data")

        # Defensive: shape not fully documented — accept a bare list or a dict
        # wrapping one under a few plausible keys, and log what we saw.
        if isinstance(data, dict):
            raw_list = (
                self._first(data, "list", "devices", "deviceList", "records") or []
            )
        elif isinstance(data, list):
            raw_list = data
        else:
            raw_list = []

        if not raw_list:
            _LOGGER.warning(
                "SmartSpa device list empty or unrecognised shape; raw data: %s", data
            )

        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            _LOGGER.debug("SmartSpa device entry keys: %s", list(entry.keys()))

            product_key = self._first(entry, "productKey", "product_key", "productkey")
            mac = self._first(entry, "mac", "deviceMac", "device_mac", "did")
            if not product_key or not mac:
                _LOGGER.warning(
                    "Skipping device entry without productKey/mac: %s", entry
                )
                continue
            mac = str(mac).lower()  # mac is lowercase in API paths

            alias = (
                self._first(
                    entry,
                    "name",
                    "alias",
                    "deviceName",
                    "device_name",
                    "nickname",
                    "remark",
                    "productName",
                )
                or "Bestway Spa"
            )
            product_name = str(
                self._first(entry, "productName", "product_name") or "UltraFit"
            )
            # The device list often carries no productName, so map known
            # productKeys to a series directly. Confirmed on live hardware:
            #   F12D9Q = Lay-Z-Spa San Francisco HydroJet Pro (EU)
            #   FTEW0E = Airjet / UltraFit (EU + US, from issue #135 reports)
            _pk_series = {"F12D9Q": "HYDROJET_PRO", "FTEW0E": "ULTRAFIT_AIRJET"}
            # The EU gateway reports availability as `onlineStatus` (1/0) in the
            # device list; `isOnline`/`is_online`/`online` are never present.
            # Aliases kept in case other regions differ.
            is_online = bool(
                self._first(entry, "onlineStatus", "isOnline", "is_online", "online")
                or False
            )

            device_id = mac
            self._routing[device_id] = (str(product_key), mac)
            self.devices[device_id] = BestwayDevice(
                protocol_version=3,
                device_id=device_id,
                product_name=product_name,
                alias=str(alias),
                mcu_soft_version="",
                mcu_hard_version="",
                wifi_soft_version="",
                wifi_hard_version="",
                is_online=is_online,
                backend=Backend.SMARTSPA,
                product_id=str(product_key),
                product_series=_pk_series.get(
                    str(product_key), self._series_from_name(product_name)
                ),
            )

        _LOGGER.info("SmartSpa discovered %d device(s)", len(self.devices))

    # ------------------------------------------------------------------ state

    async def fetch_data(self) -> BestwayApiResults:
        """Fetch the shadow for every device and normalize field names."""
        for device_id, (product_key, mac) in self._routing.items():
            try:
                result = await self._request(
                    "GET", f"app/device/shadow/{product_key}/{mac}"
                )
                shadow = result.get("data") or {}
                if not isinstance(shadow, dict):
                    shadow = {}

                # ConnectType: "online"/"offline" — surface as is_online too
                connect_type = shadow.get("ConnectType")
                if connect_type is not None:
                    shadow.setdefault(
                        "is_online", str(connect_type).lower() == "online"
                    )

                # Same field names as the AWS IoT shadow — reuse its normalizer.
                mapped = AwsIotApi.normalize_aws_state(shadow)

                # Read-back quirk: this gateway reads wave_state back as
                # binary (1, sometimes 2) while running, but the 3-way
                # bubbles select expects 0/40/100 and renders an unrecognized
                # value as OFF - making OFF unselectable (no state change)
                # while bubbles physically run. Map any binary "on" to 100 so
                # the select shows MAX and OFF becomes a real change. Writes
                # are unaffected (non-zero -> 1). Verified live on F12D9Q
                # (HydroJet Pro, EU); explains the "bubbles turn on but not
                # off" reports on on/off hardware.
                #
                # No equivalent patch is needed for the heater_state == 2
                # readback quirk: the shared V01 translator already treats
                # any non-zero heat value other than 4 (TARGET_REACHED) as
                # HeaterState.HEATING.
                if mapped.get("wave") in (1, 2):
                    mapped["wave"] = 100

                self._raw_state[device_id] = RawSnapshot(
                    timestamp=int(time()), attrs=mapped
                )
                _LOGGER.debug(
                    "SmartSpa state for %s: %s", device_id, list(mapped.keys())
                )

            except SmartSpaAuthException:
                # Authentication is not a per-device problem: re-login already
                # failed inside _request(). Let it reach the coordinator, which
                # maps it to ConfigEntryAuthFailed.
                raise
            except Exception as err:
                _LOGGER.warning(
                    "Failed to fetch SmartSpa state for %s: %s", device_id, err
                )
                # Deliberately no placeholder entry here: a RawSnapshot with
                # empty attrs would translate to a truthy DeviceStatus, which
                # passes `if not device.status` guards and then raises
                # KeyError downstream. Leaving the cache untouched keeps the
                # last known state, or no state at all.

        return self._results()

    # ---------------------------------------------------------------- control

    @staticmethod
    def _to_write_value(key: str, value: Any) -> int:
        """Translate a control value to what this backend's wire format expects.

        The semantic setters pass plain bool/int values, but this also
        accepts an IntEnum defensively (any caller going through
        set_device_state directly, bypassing the semantic setters). The
        SmartSpa gateway writes are plain 1/0 for the state datapoints
        (confirmed from proxy traces of the official app; the read-back 2 is
        a status, not a write value). temperature_setting passes through
        unchanged.
        """
        if isinstance(value, bool):
            numeric: int = 1 if value else 0
        elif hasattr(value, "value"):  # IntEnum
            numeric = int(value.value)
        else:
            numeric = int(value)

        if key in (
            "filter_state",
            "heater_state",
            "wave_state",
            "power_state",
            "hydrojet_state",
            "locked",
        ):
            # NOTE: if a 3-level-bubbles model ever shows up on this backend,
            # wave_state may need 0/40/100 passthrough — only 1/0 is confirmed.
            return 1 if numeric else 0
        return numeric

    async def set_device_state(
        self, device_id: str, state_updates: dict[str, Any]
    ) -> bool:
        """Send a control write. data MUST be a JSON string (see module docs)."""
        if device_id not in self._routing:
            _LOGGER.error("Unknown device %s", device_id)
            return False

        product_key, mac = self._routing[device_id]
        datapoints = {
            key: self._to_write_value(key, value)
            for key, value in state_updates.items()
        }
        if not datapoints:
            return False

        body = _envelope(json.dumps(datapoints, separators=(",", ":")))
        # ^ the whole point: data is a *string*. An attrs-object variant
        #   returns 200/data:true and silently does nothing.

        try:
            await self._request("POST", f"app/device/control/{product_key}/{mac}", body)
        except SmartSpaException as err:
            _LOGGER.error("Control write to %s failed: %s", device_id, err)
            return False

        # Reaching this point only means the gateway accepted the *envelope*:
        # _request() raises on any non-200 code. It is NOT a guarantee that the
        # payload was applied. Measured on the EU gateway: an unknown field, a
        # nonsensical value and an empty payload all return code 200/data:true
        # and are silently discarded. Only reading the shadow back after the
        # settle window proves a write took effect.
        _LOGGER.info(
            "SmartSpa control %s -> %s sent (writes settle in ~5-10s; "
            "filter/heater read back 2 while running)",
            datapoints,
            device_id,
        )
        return True

    # ------------------------------------------------------- semantic setters
    # Single implementation per feature; _to_write_value collapses every
    # state field to 1/0 regardless of what's passed in here.

    async def set_power(self, device_id: str, power: bool) -> None:
        """Set power state."""
        await self.set_device_state(device_id, {"power_state": power})

    async def set_filter(self, device_id: str, filtering: bool) -> None:
        """Set filter state."""
        await self.set_device_state(device_id, {"filter_state": filtering})

    async def set_heat(self, device_id: str, heat: bool) -> None:
        """Set heater state."""
        await self.set_device_state(device_id, {"heater_state": heat})

    async def set_locked(self, device_id: str, locked: bool) -> None:
        """Set panel lock."""
        await self.set_device_state(device_id, {"locked": locked})

    async def set_jets(self, device_id: str, jets: bool) -> None:
        """Set hydrojets."""
        await self.set_device_state(device_id, {"hydrojet_state": jets})

    async def set_target_temperature(self, device_id: str, temperature: int) -> None:
        """Set target temperature (device-native unit)."""
        await self.set_device_state(
            device_id, {"temperature_setting": int(temperature)}
        )

    async def set_bubbles(self, device_id: str, bubbles: BubblesLevel) -> None:
        """Set bubbles from a BubblesLevel.

        Bubbles are binary on this gateway (three-way is lost): any non-OFF
        level becomes on.
        """
        await self.set_device_state(
            device_id, {"wave_state": bubbles != BubblesLevel.OFF}
        )

    async def set_pool_timer(self, device_id: str, hours: int) -> None:
        """Set pool filter timer (untested on this backend)."""
        await self.set_device_state(device_id, {"time": int(hours)})
