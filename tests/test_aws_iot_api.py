"""Tests for AWS IoT API client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from custom_components.bestway.aws_iot.api import (
    AwsIotApi,
    AwsIotAuthException,
    AwsIotConnectionError,
    AwsIotException,
)
from custom_components.bestway.const import Backend
from custom_components.bestway.model import BestwayDevice, BubblesLevel


def create_mock_response(status: int, json_data: dict):
    """Create a properly mocked aiohttp response with context manager support."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    return response


def make_aws_device(device_id: str = "device1") -> BestwayDevice:
    """Create a V02 device for polling tests."""
    return BestwayDevice(
        protocol_version=2,
        device_id=device_id,
        product_name="AIRJET",
        alias="Test Spa",
        mcu_soft_version="unknown",
        mcu_hard_version="unknown",
        wifi_soft_version="unknown",
        wifi_hard_version="unknown",
        is_online=True,
        backend=Backend.AWS_IOT,
        product_id="T53NN8",
    )


SHADOW_RESPONSE = {
    "code": 0,
    "data": {"state": {"reported": {"power_state": 1}}},
}


@pytest.fixture
def mock_session():
    """Create mock aiohttp ClientSession."""
    session = AsyncMock()
    return session


@pytest.fixture
def aws_api(mock_session):
    """Create AwsIotApi instance for testing."""
    return AwsIotApi(
        session=mock_session,
        visitor_id="test_visitor_123",
        token="test_token_456",
        location="GB",
    )


def test_signature_deterministic(aws_api):
    """Test signature is deterministic for same inputs."""
    # Use _generate_auth_headers which returns full headers dict
    # Signature is deterministic within the same timestamp second
    headers1 = aws_api._generate_auth_headers()
    headers2 = aws_api._generate_auth_headers()

    # Both should have 'sign' field
    assert "sign" in headers1
    assert "sign" in headers2
    # Signatures should be 32-char hex strings (MD5)
    assert len(headers1["sign"]) == 32
    assert len(headers2["sign"]) == 32


def test_signature_different_for_different_inputs(aws_api):
    """Test signature changes with different inputs."""
    import time

    # Get first signature
    headers1 = aws_api._generate_auth_headers()
    sig1 = headers1["sign"]

    # Wait to ensure different timestamp
    time.sleep(1)

    # Get second signature - should be different due to timestamp change
    headers2 = aws_api._generate_auth_headers()
    sig2 = headers2["sign"]

    # Signatures include timestamp, so they should differ
    assert sig1 != sig2


@pytest.mark.asyncio
async def test_refresh_bindings_discovers_devices(aws_api, mock_session):
    """Test device discovery populates devices dict."""
    # Patch _do_get to return properly structured API responses
    homes_data = {"code": 0, "data": {"list": [{"id": "home1", "name": "My Home"}]}}
    rooms_data = {"code": 0, "data": {"list": [{"id": "room1", "name": "Garden"}]}}
    devices_data = {
        "code": 0,
        "data": {
            "list": [
                {
                    "device_id": "device123",
                    "device_alias": "Test Spa",
                    "product_series": "AIRJET",
                    "product_id": "T53NN8",
                    "service_region": "eu-central-1",
                    "is_online": True,
                }
            ]
        },
    }

    aws_api._do_get = AsyncMock(side_effect=[homes_data, rooms_data, devices_data])

    # Execute
    await aws_api.refresh_bindings()

    # Verify
    assert len(aws_api.devices) == 1
    assert "device123" in aws_api.devices

    device = aws_api.devices["device123"]
    assert device.device_id == "device123"
    assert device.alias == "Test Spa"
    assert device.backend == "aws_iot"
    assert device.protocol_version == 2
    assert device.ws_host == "eu-central-1"  # Region stored in ws_host


@pytest.mark.asyncio
async def test_refresh_bindings_multiple_devices(aws_api, mock_session):
    """Test discovery of multiple devices across rooms."""
    # 1 home, 2 rooms, 1 device per room
    homes_data = {"code": 0, "data": {"list": [{"id": "home1", "name": "My Home"}]}}
    rooms_data = {
        "code": 0,
        "data": {
            "list": [
                {"id": "room1", "name": "Garden"},
                {"id": "room2", "name": "Patio"},
            ]
        },
    }
    devices1_data = {
        "code": 0,
        "data": {
            "list": [
                {
                    "device_id": "device1",
                    "device_alias": "Spa 1",
                    "product_series": "AIRJET",
                    "product_id": "T53NN8",
                    "service_region": "eu-central-1",
                }
            ]
        },
    }
    devices2_data = {
        "code": 0,
        "data": {
            "list": [
                {
                    "device_id": "device2",
                    "device_alias": "Spa 2",
                    "product_series": "HYDROJET",
                    "product_id": "T53NN9",
                    "service_region": "us-east-1",
                }
            ]
        },
    }

    aws_api._do_get = AsyncMock(
        side_effect=[homes_data, rooms_data, devices1_data, devices2_data]
    )

    await aws_api.refresh_bindings()

    assert len(aws_api.devices) == 2
    assert "device1" in aws_api.devices
    assert "device2" in aws_api.devices
    assert aws_api.devices["device1"].alias == "Spa 1"
    assert aws_api.devices["device2"].alias == "Spa 2"


@pytest.mark.asyncio
async def test_fetch_data_returns_results(aws_api, mock_session):
    """Test fetch_data returns BestwayApiResults."""
    # Setup device with real attributes (not MagicMock) so JSON serialization works
    aws_api.devices = {
        "device1": BestwayDevice(
            protocol_version=2,
            device_id="device1",
            product_name="AIRJET",
            alias="Test Spa",
            mcu_soft_version="unknown",
            mcu_hard_version="unknown",
            wifi_soft_version="unknown",
            wifi_hard_version="unknown",
            is_online=True,
            backend="aws_iot",
            product_id="T53NN8",
        )
    }

    # Patch _do_post to return properly structured shadow response
    shadow_data = {
        "code": 0,
        "data": {
            "state": {
                "reported": {
                    "power_state": 1,
                    "heater_state": 3,
                    "temperature_setting": 37,
                    "water_temperature": 36,
                }
            }
        },
    }
    aws_api._do_post = AsyncMock(return_value=shadow_data)

    # Execute
    results = await aws_api.fetch_data()

    # Verify structure
    assert hasattr(results, "devices")
    assert "device1" in results.devices

    status = results.devices["device1"]
    assert status.attrs["power"] is True
    assert status.attrs["heat"] == 3
    assert status.attrs["Tset"] == 37
    assert status.attrs["Tnow"] == 36


@pytest.mark.asyncio
async def test_set_device_state_sends_command(aws_api, mock_session):
    """Test control command sends encrypted payload."""
    # Setup device with real attributes for JSON serialization
    aws_api.devices = {
        "device1": BestwayDevice(
            protocol_version=2,
            device_id="device1",
            product_name="AIRJET",
            alias="Test Spa",
            mcu_soft_version="unknown",
            mcu_hard_version="unknown",
            wifi_soft_version="unknown",
            wifi_hard_version="unknown",
            is_online=True,
            backend="aws_iot",
            product_id="T53NN8",
        )
    }

    # Mock the v2 POST to succeed
    v2_response = create_mock_response(200, {"code": 0})
    mock_session.post = MagicMock(return_value=v2_response)

    # Execute
    success = await aws_api.set_device_state("device1", {"power_state": True})

    # Verify
    assert success is True
    assert mock_session.post.called


@pytest.mark.asyncio
async def test_do_get_handles_401(aws_api, mock_session):
    """Test _do_get raises AwsIotAuthException on HTTP 401."""
    response = create_mock_response(401, {})

    mock_session.get = MagicMock(return_value=response)

    with pytest.raises(AwsIotAuthException):
        await aws_api._do_get("/test")


# ---------------------------------------------------------------------------
# Semantic setters: single vocabulary, no per-device dispatch. Each setter
# is checked against the exact dict handed to set_device_state.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_power(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_power("device1", True)
    aws_api.set_device_state.assert_awaited_once_with("device1", {"power_state": 1})


@pytest.mark.asyncio
async def test_set_filter(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_filter("device1", False)
    aws_api.set_device_state.assert_awaited_once_with("device1", {"filter_state": 0})


@pytest.mark.asyncio
async def test_set_heat(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_heat("device1", True)
    aws_api.set_device_state.assert_awaited_once_with("device1", {"heater_state": 1})


@pytest.mark.asyncio
async def test_set_locked(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_locked("device1", True)
    aws_api.set_device_state.assert_awaited_once_with("device1", {"locked": 1})


@pytest.mark.asyncio
async def test_set_jets(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_jets("device1", True)
    aws_api.set_device_state.assert_awaited_once_with("device1", {"hydrojet_state": 1})


@pytest.mark.asyncio
async def test_set_target_temperature(aws_api):
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_target_temperature("device1", 38)
    aws_api.set_device_state.assert_awaited_once_with(
        "device1", {"temperature_setting": 38}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "wave_state"),
    [(BubblesLevel.OFF, 0), (BubblesLevel.MEDIUM, 40), (BubblesLevel.MAX, 100)],
)
async def test_set_bubbles(aws_api, level: BubblesLevel, wave_state: int):
    """V02 uses 40 for MEDIUM, not the V01 map's 50."""
    aws_api.set_device_state = AsyncMock()
    await aws_api.set_bubbles("device1", level)
    aws_api.set_device_state.assert_awaited_once_with(
        "device1", {"wave_state": wave_state}
    )


@pytest.mark.asyncio
async def test_set_pool_timer_not_supported(aws_api):
    with pytest.raises(NotImplementedError):
        await aws_api.set_pool_timer("device1", 6)


@pytest.mark.asyncio
async def test_authenticate_wraps_timeout_as_connection_error(mock_session):
    """A stalled login is transient, and must be distinguishable as such."""
    mock_session.post = MagicMock(side_effect=TimeoutError)

    with pytest.raises(AwsIotConnectionError):
        await AwsIotApi.authenticate(mock_session, "test_visitor")


@pytest.mark.asyncio
async def test_authenticate_names_a_cause_that_has_no_message(mock_session):
    """A bare TimeoutError has an empty str(), and this message becomes the
    config entry's failure reason. Without naming the type it says nothing.
    """
    mock_session.post = MagicMock(side_effect=TimeoutError)

    with pytest.raises(AwsIotConnectionError) as err:
        await AwsIotApi.authenticate(mock_session, "test_visitor")

    assert "TimeoutError" in str(err.value)


@pytest.mark.asyncio
async def test_authenticate_keeps_a_cause_that_explains_itself(mock_session):
    """A transport error carrying a message keeps it, so the reason can
    distinguish a refused connection from a timeout.
    """
    mock_session.post = MagicMock(side_effect=ClientError("connection refused"))

    with pytest.raises(AwsIotConnectionError) as err:
        await AwsIotApi.authenticate(mock_session, "test_visitor")

    assert "connection refused" in str(err.value)


@pytest.mark.asyncio
async def test_authenticate_wraps_an_expired_deadline(mock_session, monkeypatch):
    """The login outliving TIMEOUT is the reported failure, so exercise it.

    `asyncio.timeout` cancels the in-flight request and converts that into a
    TimeoutError as it unwinds, which is only catchable outside the timeout
    block. A mock raising TimeoutError directly never proves that placement
    is right.
    """
    monkeypatch.setattr("custom_components.bestway.aws_iot.api.TIMEOUT", 0.05)

    class HangingRequest:
        async def __aenter__(self):
            await asyncio.sleep(10)

        async def __aexit__(self, *args):
            return None

    mock_session.post = MagicMock(return_value=HangingRequest())

    with pytest.raises(AwsIotConnectionError):
        await AwsIotApi.authenticate(mock_session, "test_visitor")


@pytest.mark.asyncio
async def test_authenticate_rejects_missing_token(mock_session):
    """A 200 response carrying no token is a rejection, not a retry."""
    mock_session.post = MagicMock(
        return_value=create_mock_response(200, {"code": 1, "data": {}})
    )

    with pytest.raises(AwsIotAuthException):
        await AwsIotApi.authenticate(mock_session, "test_visitor")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_authenticate_checks_rejection_before_parsing_body(mock_session, status):
    """A non-JSON rejection stays a rejection.

    Parsing the body first turns it into a ContentTypeError, which is a
    ClientError, which would be classified as transient and retried forever
    against credentials the cloud has already refused.
    """
    response = create_mock_response(status, {})
    response.json = AsyncMock(side_effect=AssertionError("body must not be parsed"))
    mock_session.post = MagicMock(return_value=response)

    with pytest.raises(AwsIotAuthException):
        await AwsIotApi.authenticate(mock_session, "test_visitor")

    response.json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_do_post_checks_auth_status_before_parsing_body(
    aws_api, mock_session, status
):
    """A non-JSON auth rejection during a poll still triggers reauthentication."""
    response = create_mock_response(status, {})
    response.json = AsyncMock(side_effect=AssertionError("body must not be parsed"))
    mock_session.post = MagicMock(return_value=response)

    with pytest.raises(AwsIotAuthException):
        await aws_api._do_post("/test", {})

    response.json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_do_get_checks_auth_status_before_parsing_body(
    aws_api, mock_session, status
):
    """Same ordering guarantee on the discovery path."""
    response = create_mock_response(status, {})
    response.json = AsyncMock(side_effect=AssertionError("body must not be parsed"))
    mock_session.get = MagicMock(return_value=response)

    with pytest.raises(AwsIotAuthException):
        await aws_api._do_get("/test")

    response.json.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_data_reauthenticates_and_propagates_token(aws_api):
    """A rejected poll refreshes the token once and polls again."""
    aws_api.devices = {"device1": make_aws_device()}
    aws_api._do_post = AsyncMock(
        side_effect=[AwsIotAuthException("expired"), SHADOW_RESPONSE]
    )
    token_updated = MagicMock()
    aws_api.set_token_update_callback(token_updated)

    with patch.object(
        AwsIotApi, "authenticate", new=AsyncMock(return_value="fresh_token")
    ):
        results = await aws_api.fetch_data()

    assert results.devices["device1"].attrs["power"] is True
    assert aws_api._token == "fresh_token"
    token_updated.assert_called_once_with("fresh_token")


@pytest.mark.asyncio
async def test_fetch_data_reauthenticates_after_partial_auth_failure(aws_api):
    """One rejected device is enough: the token is shared by the account."""
    aws_api.devices = {
        "device1": make_aws_device("device1"),
        "device2": make_aws_device("device2"),
    }
    aws_api._do_post = AsyncMock(
        side_effect=[
            SHADOW_RESPONSE,
            AwsIotAuthException("expired"),
            SHADOW_RESPONSE,
            SHADOW_RESPONSE,
        ]
    )

    with patch.object(
        AwsIotApi, "authenticate", new=AsyncMock(return_value="fresh_token")
    ) as authenticate:
        results = await aws_api.fetch_data()

    authenticate.assert_awaited_once()
    assert set(results.devices) == {"device1", "device2"}
    assert aws_api._do_post.await_count == 4


@pytest.mark.asyncio
async def test_fetch_data_reraises_auth_exception_when_reauth_rejected(aws_api):
    """A rejected refresh surfaces as an auth failure, not an update failure."""
    aws_api.devices = {"device1": make_aws_device()}
    aws_api._do_post = AsyncMock(side_effect=AwsIotAuthException("expired"))

    with (
        patch.object(
            AwsIotApi,
            "authenticate",
            new=AsyncMock(side_effect=AwsIotAuthException("rejected")),
        ),
        pytest.raises(AwsIotAuthException),
    ):
        await aws_api.fetch_data()


@pytest.mark.asyncio
async def test_fetch_data_raises_connection_error_when_reauth_unreachable(aws_api):
    """An unreachable refresh is transient and must stay distinguishable."""
    aws_api.devices = {"device1": make_aws_device()}
    aws_api._do_post = AsyncMock(side_effect=AwsIotAuthException("expired"))

    with (
        patch.object(
            AwsIotApi,
            "authenticate",
            new=AsyncMock(side_effect=AwsIotConnectionError("unreachable")),
        ),
        pytest.raises(AwsIotConnectionError),
    ):
        await aws_api.fetch_data()


@pytest.mark.asyncio
async def test_fetch_data_raises_when_no_device_refreshes(aws_api):
    """A total poll failure must not be reported as a successful update.

    Returning the cache here is what let a dead session keep serving stale
    state as though the spa were healthy.
    """
    aws_api.devices = {"device1": make_aws_device()}
    aws_api._do_post = AsyncMock(side_effect=ConnectionError("offline"))

    with pytest.raises(AwsIotException):
        await aws_api.fetch_data()


@pytest.mark.asyncio
async def test_fetch_data_tolerates_partial_poll_failure(aws_api):
    """One reachable device is enough to call the update a success."""
    aws_api.devices = {
        "device1": make_aws_device("device1"),
        "device2": make_aws_device("device2"),
    }
    aws_api._do_post = AsyncMock(
        side_effect=[SHADOW_RESPONSE, ConnectionError("offline")]
    )

    results = await aws_api.fetch_data()

    assert results.devices["device1"].attrs["power"] is True


@pytest.mark.asyncio
async def test_fetch_data_with_no_devices_does_not_raise(aws_api):
    """An account with nothing bound is not a failure."""
    aws_api.devices = {}

    results = await aws_api.fetch_data()

    assert results.devices == {}


def test_update_token_without_callback(aws_api):
    """The callback is optional; the token still changes without one."""
    aws_api.update_token("fresh_token")

    assert aws_api._token == "fresh_token"
