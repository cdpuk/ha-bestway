"""Tests for the Smart Home (Gizwits AEP) API client.

All external Bestway API calls are mocked. Every share id, token and MAC used
here is fictitious.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bestway.const import BACKEND_SMART_HOME
from custom_components.bestway.smart_home.api import (
    SmartHomeApi,
    SmartHomeAuthException,
    SmartHomeException,
    SmartHomeShareException,
    parse_share_input,
)

# Fictitious values — not real credentials.
FAKE_SHARE_ID = "0123456789abcdef0123456789abcdef"
FAKE_TOKEN = "test-session-token"
FAKE_MAC = "aabbccddeeff"
FAKE_PRODUCT_KEY = "FTEW0E"
EU_URL = (
    "https://smart-spa-eu-app.bestwaycorp.com/app/"
    "0000000000000000000000000000abcd/shareDevice/index.html"
    f"?shareId={FAKE_SHARE_ID}"
)
US_URL = (
    "https://smart-spa-us-app.bestwaycorp.com/app/x/shareDevice/index.html"
    f"?shareId={FAKE_SHARE_ID}"
)


def _cm(json_data: dict, status: int = 200):
    """Build a mocked aiohttp response usable as an async context manager."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


def _session(*responses):
    """Mock ClientSession whose .request() yields the given responses in order."""
    session = MagicMock()
    session.request = MagicMock(side_effect=list(responses))
    return session


def _ok(data):
    return {"code": "200", "message": "ok", "data": data, "error": False}


# --- parse_share_input -------------------------------------------------------


def test_parse_full_eu_url():
    """A full EU share URL yields the share id and EU region."""
    share_id, region = parse_share_input(EU_URL)
    assert share_id == FAKE_SHARE_ID
    assert region == "EU"


def test_parse_full_us_url():
    """A US share URL yields the US region."""
    share_id, region = parse_share_input(US_URL)
    assert share_id == FAKE_SHARE_ID
    assert region == "US"


def test_parse_bare_share_id():
    """A bare hex share id is accepted with no region."""
    share_id, region = parse_share_input(FAKE_SHARE_ID)
    assert share_id == FAKE_SHARE_ID
    assert region is None


def test_parse_url_without_share_id():
    """A share URL missing the shareId parameter is rejected clearly."""
    url = "https://smart-spa-eu-app.bestwaycorp.com/app/x/shareDevice/index.html"
    with pytest.raises(SmartHomeShareException) as err:
        parse_share_input(url)
    assert str(err.value) == "missing_share_id"


def test_parse_empty_input():
    """Empty input is rejected as a missing share id."""
    with pytest.raises(SmartHomeShareException) as err:
        parse_share_input("   ")
    assert str(err.value) == "missing_share_id"


def test_parse_invalid_garbage():
    """Non-URL, non-hex input is rejected as an invalid share id."""
    with pytest.raises(SmartHomeShareException) as err:
        parse_share_input("INVALID_QR_123")
    assert str(err.value) == "invalid_share_id"


def test_parse_unexpected_share_id_format():
    """A shareId that isn't hex is rejected as invalid, not accepted blindly."""
    url = (
        "https://smart-spa-eu-app.bestwaycorp.com/app/x/shareDevice/index.html"
        "?shareId=not-a-valid-id"
    )
    with pytest.raises(SmartHomeShareException) as err:
        parse_share_input(url)
    assert str(err.value) == "invalid_share_id"


def test_parse_unknown_host_still_uses_share_id():
    """An unrecognised host falls back to no region but keeps a valid share id."""
    url = f"https://example.com/whatever?shareId={FAKE_SHARE_ID}"
    share_id, region = parse_share_input(url)
    assert share_id == FAKE_SHARE_ID
    assert region is None


# --- authenticate ------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_returns_token():
    """A successful anonymous login returns the session token."""
    session = _session(_cm(_ok({"userToken": FAKE_TOKEN, "refreshToken": "r"})))
    token = await SmartHomeApi.authenticate(session, "phone-id")
    assert token == FAKE_TOKEN


@pytest.mark.asyncio
async def test_authenticate_missing_token_raises():
    """A login response without a token raises an auth exception."""
    session = _session(_cm(_ok({})))
    with pytest.raises(SmartHomeAuthException):
        await SmartHomeApi.authenticate(session, "phone-id")


@pytest.mark.asyncio
async def test_authenticate_error_code_raises():
    """A non-200 business code raises."""
    session = _session(_cm({"code": "500", "error": True, "data": None}))
    with pytest.raises(SmartHomeException):
        await SmartHomeApi.authenticate(session, "phone-id")


# --- accept_share ------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_share_success():
    """A 200 response redeems the share without error."""
    session = _session(_cm(_ok(FAKE_SHARE_ID)))
    await SmartHomeApi.accept_share(session, FAKE_SHARE_ID, FAKE_TOKEN)


@pytest.mark.asyncio
async def test_accept_share_already_used():
    """Code 2000066 maps to a clear 'already used' error."""
    session = _session(
        _cm({"code": "2000066", "message": "already shared", "error": True})
    )
    with pytest.raises(SmartHomeShareException) as err:
        await SmartHomeApi.accept_share(session, FAKE_SHARE_ID, FAKE_TOKEN)
    assert str(err.value) == "share_already_used"


@pytest.mark.asyncio
async def test_accept_share_invalid_id():
    """Code 4000002 maps to an invalid-share-id error."""
    session = _session(_cm({"code": "4000002", "error": True}))
    with pytest.raises(SmartHomeShareException) as err:
        await SmartHomeApi.accept_share(session, FAKE_SHARE_ID, FAKE_TOKEN)
    assert str(err.value) == "invalid_share_id"


@pytest.mark.asyncio
async def test_accept_share_device_not_found():
    """Code 2000001 maps to a device-not-found error."""
    session = _session(_cm({"code": "2000001", "error": True}))
    with pytest.raises(SmartHomeShareException) as err:
        await SmartHomeApi.accept_share(session, FAKE_SHARE_ID, FAKE_TOKEN)
    assert str(err.value) == "device_not_found"


# --- refresh_bindings + fetch_data ------------------------------------------


@pytest.mark.asyncio
async def test_refresh_bindings_builds_devices():
    """Device discovery maps the API list into BestwayDevice objects."""
    device_list = [
        {
            "mac": FAKE_MAC,
            "productKey": FAKE_PRODUCT_KEY,
            "name": "Toronto",
            "onlineStatus": 1,
        }
    ]
    api = SmartHomeApi(_session(_cm(_ok(device_list))), "phone-id", token=FAKE_TOKEN)
    await api.refresh_bindings()

    assert FAKE_MAC in api.devices
    device = api.devices[FAKE_MAC]
    assert device.backend == BACKEND_SMART_HOME
    assert device.product_id == FAKE_PRODUCT_KEY
    assert device.product_series == "ULTRAFIT_AIRJET"
    assert device.alias == "Toronto"
    assert device.is_online is True


@pytest.mark.asyncio
async def test_refresh_bindings_skips_incomplete_entries():
    """Entries missing a mac or productKey are skipped, not crashed on."""
    device_list = [{"productKey": FAKE_PRODUCT_KEY}, {"mac": FAKE_MAC}]
    api = SmartHomeApi(_session(_cm(_ok(device_list))), "phone-id", token=FAKE_TOKEN)
    await api.refresh_bindings()
    assert api.devices == {}


@pytest.mark.asyncio
async def test_fetch_data_normalizes_shadow():
    """Shadow fields are normalised into the shared V01 attribute names."""
    shadow = {
        "power_state": 1,
        "water_temperature": 35,
        "temperature_setting": 37,
        "wave_state": 0,
        "filter_state": 2,
        "heater_state": 4,
    }
    device_list = [
        {
            "mac": FAKE_MAC,
            "productKey": FAKE_PRODUCT_KEY,
            "name": "x",
            "onlineStatus": 1,
        }
    ]
    api = SmartHomeApi(
        _session(_cm(_ok(device_list)), _cm(_ok(shadow))),
        "phone-id",
        token=FAKE_TOKEN,
    )
    await api.refresh_bindings()
    results = await api.fetch_data()

    attrs = results.devices[FAKE_MAC].attrs
    assert attrs["power"] is True
    assert attrs["Tnow"] == 35
    assert attrs["Tset"] == 37


# --- set_device_state --------------------------------------------------------


@pytest.mark.asyncio
async def test_set_device_state_sends_plaintext_command():
    """Control commands post plaintext JSON field names to the control path."""
    api = SmartHomeApi(MagicMock(), "phone-id", token=FAKE_TOKEN)
    api.devices = await _one_device(api)
    api._request = AsyncMock(return_value=_ok(True))

    await api.airjet_spa_set_bubbles(FAKE_MAC, True)

    method, path = api._request.call_args.args[0], api._request.call_args.args[1]
    body = api._request.call_args.kwargs["json_body"]
    assert method == "POST"
    assert path == f"/app/device/control/{FAKE_PRODUCT_KEY}/{FAKE_MAC}"
    # `data` is a JSON *string* of the desired fields.
    assert body["data"] == '{"wave_state":1}'


@pytest.mark.asyncio
async def test_set_target_temp_command():
    """Target temperature is sent as an integer field."""
    api = SmartHomeApi(MagicMock(), "phone-id", token=FAKE_TOKEN)
    api.devices = await _one_device(api)
    api._request = AsyncMock(return_value=_ok(True))

    await api.airjet_spa_set_target_temp(FAKE_MAC, 38)
    assert api._request.call_args.kwargs["json_body"]["data"] == (
        '{"temperature_setting":38}'
    )


async def _one_device(api: SmartHomeApi):
    """Helper: a single discovered device dict for control tests."""
    from custom_components.bestway.bestway.model import BestwayDevice

    return {
        FAKE_MAC: BestwayDevice(
            protocol_version=2,
            device_id=FAKE_MAC,
            product_name="ULTRAFIT_AIRJET",
            alias="Toronto",
            mcu_soft_version="x",
            mcu_hard_version="x",
            wifi_soft_version="x",
            wifi_hard_version="x",
            is_online=True,
            backend=BACKEND_SMART_HOME,
            product_id=FAKE_PRODUCT_KEY,
            product_series="ULTRAFIT_AIRJET",
        )
    }
