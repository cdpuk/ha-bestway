"""Tests for the SmartSpa gateway API client (post-July-2026 Bestway Connect).

Covers the auth workflow, data updates, and the backend-specific quirks
documented in https://github.com/cdpuk/ha-bestway/issues/135:

* control ``data`` must be a stringified JSON (attrs-object silently no-ops)
* writes are 1/0 but filter/heater read back 2 while running
* code 505 (token invalidated server-side) triggers one re-login + retry
* device list arrives in loosely documented shapes
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bestway.smartspa.api import (
    SMARTSPA_APP_ID,
    SmartSpaApi,
    SmartSpaAuthException,
    SmartSpaException,
    _content_md5,
    _envelope,
)


def create_mock_response(status: int, json_data: dict):
    """Create a properly mocked aiohttp response with context manager support."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


@pytest.fixture
def mock_session():
    """Create mock aiohttp ClientSession.

    post/request are sync callables returning async-context-manager
    responses, matching how aiohttp is actually used (``async with
    session.post(...)``).
    """
    session = AsyncMock()
    session.post = MagicMock()
    session.request = MagicMock()
    return session


@pytest.fixture
def api(mock_session):
    """Create a SmartSpaApi with a valid token and one known device."""
    client = SmartSpaApi(
        session=mock_session,
        account="user@example.com",
        password="hunter2",
        api_base="https://smart-spa-eu-app.bestwaycorp.com",
        token="valid_token",
    )
    client._routing["6879c4d585ab"] = ("F12D9Q", "6879c4d585ab")
    return client


# ---------------------------------------------------------------------- auth


async def test_authenticate_success(mock_session):
    """Login posts the envelope and returns data.userToken."""
    mock_session.post.return_value = create_mock_response(
        200, {"code": "200", "data": {"userToken": "tok123"}, "error": False}
    )

    token = await SmartSpaApi.authenticate(
        mock_session, "user@example.com", "hunter2", "https://host"
    )

    assert token == "tok123"
    args, kwargs = mock_session.post.call_args
    assert args[0] == "https://host/app/smart_home/login/pwd"
    body = json.loads(kwargs["data"].decode())
    # Envelope shape: appKey + data + version
    assert body["appKey"] == SMARTSPA_APP_ID
    assert body["version"] == "1.0"
    assert body["data"]["account"] == "user@example.com"
    # Content-MD5 must match base64(md5(body))
    sent_body = kwargs["data"].decode()
    assert kwargs["headers"]["Content-MD5"] == _content_md5(sent_body)
    assert kwargs["headers"]["X-Gizwits-Application-Id"] == SMARTSPA_APP_ID


async def test_authenticate_bad_credentials(mock_session):
    """A non-200 code raises an auth error with the server message."""
    mock_session.post.return_value = create_mock_response(
        200, {"code": "401", "message": "bad password", "data": None}
    )

    with pytest.raises(SmartSpaAuthException):
        await SmartSpaApi.authenticate(mock_session, "u", "p", "https://host")


async def test_authenticate_missing_token(mock_session):
    """code 200 without a userToken is still an auth failure."""
    mock_session.post.return_value = create_mock_response(
        200, {"code": "200", "data": {"something": "else"}}
    )

    with pytest.raises(SmartSpaAuthException):
        await SmartSpaApi.authenticate(mock_session, "u", "p", "https://host")


async def test_request_relogin_on_505(api, mock_session):
    """code 505 (token invalidated server-side) re-authenticates and retries once.

    Without this, control writes silently stop working when the gateway
    expires the token (reads happen to recover on their own, writes don't).
    """
    mock_session.request.side_effect = [
        create_mock_response(200, {"code": "505", "message": "not logged in"}),
        create_mock_response(200, {"code": "200", "data": True}),
    ]
    api.authenticate = AsyncMock(return_value="fresh_token")

    result = await api._request("POST", "app/device/control/F12D9Q/6879c4d585ab", {})

    assert result["data"] is True
    api.authenticate.assert_awaited_once()
    assert api._token == "fresh_token"
    # Second attempt must carry the fresh token
    _, second_kwargs = mock_session.request.call_args
    assert second_kwargs["headers"]["Authorization"] == "fresh_token"


async def test_request_505_twice_raises(api, mock_session):
    """If re-login doesn't help, the request fails rather than looping."""
    mock_session.request.side_effect = [
        create_mock_response(200, {"code": "505"}),
        create_mock_response(200, {"code": "505"}),
    ]
    api.authenticate = AsyncMock(return_value="fresh_token")

    with pytest.raises(SmartSpaException):
        await api._request("GET", "app/smart_home/users/devices")


def test_bare_token_in_authorization_header(api):
    """Token goes bare into Authorization (Bearer/x-gizwits-user-token fail)."""
    headers = api._headers(None)
    assert headers["Authorization"] == "valid_token"
    assert not headers["Authorization"].startswith("Bearer")
    assert "Content-MD5" not in headers  # no body -> no MD5


# ----------------------------------------------------------------- discovery


async def test_refresh_bindings_real_world_shape(api):
    """Parse the device list shape observed on the live EU gateway."""
    api._routing.clear()
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": [
                {
                    "sno": "11247711082452855093",
                    "productKey": "F12D9Q",
                    "mac": "6879C4D585AB",
                    "name": "Loovemachine",
                    "roomId": 3234,
                    "did": "11247711082452855093",
                    "onlineStatus": 1,
                }
            ],
        }
    )

    await api.refresh_bindings()

    assert len(api.devices) == 1
    device = api.devices["6879c4d585ab"]
    assert device.alias == "Loovemachine"
    assert device.product_id == "F12D9Q"
    # Known productKey maps to series even without a productName field
    assert device.product_series == "HYDROJET_PRO"
    # mac is lowercased for API paths
    assert api._routing["6879c4d585ab"] == ("F12D9Q", "6879c4d585ab")
    # The live gateway reports availability as `onlineStatus`
    assert device.is_online is True


async def test_refresh_bindings_wrapped_list_shapes(api):
    """Device list may arrive wrapped in a dict under various keys."""
    for wrapper in ({"list": []}, {"devices": []}, {"deviceList": []}):
        wrapper_key = next(iter(wrapper))
        api.devices.clear()
        api._routing.clear()
        api._request = AsyncMock(
            return_value={
                "code": "200",
                "data": {
                    wrapper_key: [{"productKey": "FTEW0E", "mac": "aabbccddeeff"}]
                },
            }
        )
        await api.refresh_bindings()
        assert len(api.devices) == 1, f"failed for wrapper key {wrapper_key!r}"
        assert api.devices["aabbccddeeff"].product_series == "ULTRAFIT_AIRJET"


async def test_refresh_bindings_cached_after_success(api):
    """Discovery only hits the API once; later calls use the cache."""
    api._routing.clear()
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": [{"productKey": "F12D9Q", "mac": "6879c4d585ab"}],
        }
    )
    await api.refresh_bindings()
    await api.refresh_bindings()
    api._request.assert_awaited_once()


# --------------------------------------------------------------------- state


async def test_fetch_data_normalizes_shadow(api):
    """Shadow fields map to the friendly names entities read."""
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": {
                "water_temperature": 33,
                "temperature_setting": 39,
                "temperature_unit": 1,
                "power_state": 1,
                "heater_state": 0,
                "filter_state": 2,
                "wave_state": 0,
                "hydrojet_state": 0,
                "ConnectType": "online",
                "error_code": 0,
                "warning": 0,
            },
        }
    )

    results = await api.fetch_data()

    attrs = results.devices["6879c4d585ab"].attrs
    assert attrs["Tnow"] == 33
    assert attrs["Tset"] == 39
    assert attrs["power"] is True
    # Quirk: filter reads back 2 while running; entities treat truthy as on
    assert attrs["filter"] == 2
    assert attrs["is_online"] is True


async def test_fetch_data_heater_readback_two_maps_to_heating(api):
    """heater_state reads 2 while heating; climate knows 3 (HEATING)."""
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": {"heater_state": 2, "ConnectType": "online"},
        }
    )

    results = await api.fetch_data()

    assert results.devices["6879c4d585ab"].attrs["heat"] == 3


async def test_fetch_data_survives_one_failing_device(api):
    """One device erroring must not break the poll for the others."""
    api._routing["aabbccddeeff"] = ("FTEW0E", "aabbccddeeff")

    async def request_side_effect(method, path, body=None):
        if "6879c4d585ab" in path:
            raise SmartSpaException("boom")
        return {"code": "200", "data": {"water_temperature": 30}}

    api._request = AsyncMock(side_effect=request_side_effect)

    results = await api.fetch_data()

    # The failing device gets no entry at all. A placeholder with empty attrs
    # would be truthy, pass `if not device.status` guards, and then raise
    # KeyError downstream; absence makes its entities unavailable instead.
    assert "6879c4d585ab" not in results.devices
    assert results.devices["aabbccddeeff"].attrs["Tnow"] == 30


async def test_fetch_data_propagates_auth_failure(api):
    """An auth failure must not be swallowed as a per-device error.

    _request() only raises SmartSpaAuthException once its own re-login has
    already failed, so the stored credentials are genuinely bad. Treating that
    like a transient per-device glitch would hide it behind a warning and leave
    the integration silently returning stale data forever. The coordinator maps
    it to ConfigEntryAuthFailed instead.
    """
    api._request = AsyncMock(side_effect=SmartSpaAuthException("no session"))

    with pytest.raises(SmartSpaAuthException):
        await api.fetch_data()


# ------------------------------------------------------------------- control


async def test_control_data_is_stringified_json(api):
    """The control body's data field MUST be a JSON string.

    The attrs-object variant returns 200/data:true and silently does
    nothing - this is the core trap the #135 thread lost weeks to.
    """
    api._request = AsyncMock(return_value={"code": "200", "data": True})

    ok = await api.set_device_state("6879c4d585ab", {"filter_state": 1})

    assert ok is True
    _, path, body = api._request.call_args[0]
    assert path == "app/device/control/F12D9Q/6879c4d585ab"
    assert isinstance(body["data"], str)
    assert json.loads(body["data"]) == {"filter_state": 1}
    assert "attrs" not in body


async def test_control_translates_legacy_write_values(api):
    """Entity layer passes 2/3/40/100; this gateway writes plain 1/0."""
    api._request = AsyncMock(return_value={"code": "200", "data": True})

    # HydrojetFilter.ON == 2, HydrojetHeat.ON == 3, bubbles max == 100
    await api.hydrojet_spa_set_filter("6879c4d585ab", 2)
    await api.hydrojet_spa_set_heat("6879c4d585ab", 3)
    await api.airjet_spa_set_bubbles("6879c4d585ab", True)
    await api.hydrojet_spa_set_target_temp("6879c4d585ab", 39)

    sent = [json.loads(call[0][2]["data"]) for call in api._request.call_args_list]
    assert sent[0] == {"filter_state": 1}
    assert sent[1] == {"heater_state": 1}
    assert sent[2] == {"wave_state": 1}
    # temperature passes through untranslated
    assert sent[3] == {"temperature_setting": 39}


async def test_control_off_values(api):
    """Off writes send 0 (the bubbles-off path from the PR thread)."""
    api._request = AsyncMock(return_value={"code": "200", "data": True})

    await api.airjet_spa_set_bubbles("6879c4d585ab", False)
    await api.hydrojet_spa_set_filter("6879c4d585ab", 0)

    sent = [json.loads(call[0][2]["data"]) for call in api._request.call_args_list]
    assert sent[0] == {"wave_state": 0}
    assert sent[1] == {"filter_state": 0}


async def test_control_unknown_device_returns_false(api):
    """Writes to unknown devices fail cleanly without a request."""
    api._request = AsyncMock()

    ok = await api.set_device_state("ffffffffffff", {"power_state": 1})

    assert ok is False
    api._request.assert_not_awaited()


def test_envelope_shape():
    """The request envelope carries appKey/data/version."""
    body = _envelope(json.dumps({"power_state": 1}))
    assert body["appKey"] == SMARTSPA_APP_ID
    assert body["version"] == "1.0"
    assert isinstance(body["data"], str)


def test_write_value_returns_int():
    """_to_write_value always returns int (mypy: no Any leaks)."""
    assert SmartSpaApi._to_write_value("filter_state", True) == 1
    assert SmartSpaApi._to_write_value("filter_state", 2) == 1
    assert SmartSpaApi._to_write_value("wave_state", 100) == 1
    assert SmartSpaApi._to_write_value("wave_state", 0) == 0
    assert SmartSpaApi._to_write_value("temperature_setting", 39) == 39
    for value in (True, 2, 100, 0):
        assert isinstance(SmartSpaApi._to_write_value("filter_state", value), int)
