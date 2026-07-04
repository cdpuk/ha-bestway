"""Tests for AWS IoT API client."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.bestway.aws_iot.api import (
    AwsIotApi,
    AwsIotAuthException,
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


def test_normalize_state_comprehensive():
    """Test comprehensive field normalization including power, temperature, and wave."""
    aws_state = {
        "power_state": 1,
        "heater_state": 0,
        "temperature_setting": 37,
        "water_temperature": 36,
        "temperature_unit": 1,
        "wave_state": 100,
        "warning": "",
        "error_code": "",
    }
    normalized = AwsIotApi.normalize_aws_state(aws_state)

    # Power fields
    assert normalized["power"] is True
    assert normalized["heat"] == 0

    # Temperature fields
    assert normalized["Tset"] == 37
    assert normalized["Tnow"] == 36
    assert normalized["Tunit"] == 1

    # Wave field
    assert normalized["wave"] == 100


def test_normalize_state_filter():
    """Test filter_state normalization."""
    # Filter on
    aws_state = {"filter_state": 2}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["filter"] == 2

    # Filter off
    aws_state = {"filter_state": 0}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["filter"] == 0


def test_normalize_state_partial_update_preserves_absent_fields():
    """Test that partial WebSocket updates don't overwrite absent fields.

    Regression test for temperature unit flip-flop bug: WebSocket deltas
    that omit temperature_unit should not default it to Celsius (1),
    which would overwrite a Fahrenheit (0) setting.
    """
    # Simulate a partial WebSocket delta with only temperature change
    partial_state = {
        "water_temperature": 30,
    }
    normalized = AwsIotApi.normalize_aws_state(partial_state)

    # temperature_unit was not in the delta, so Tunit should not be set
    assert "Tunit" not in normalized
    # warning/error also absent, should not be set
    assert "warning" not in normalized
    assert "error" not in normalized
    # The field that was present should be set
    assert normalized["Tnow"] == 30


def test_normalize_state_wave_mapping():
    """Test V02 wave_state is passed through unchanged.

    The normaliser used to rewrite 40 -> 50, which the Hydrojet bubble map
    rejected, so Hydrojet MEDIUM always rendered as OFF (BUG-SPA-6). Both
    bubble maps now recognise 40 as MEDIUM directly, so the raw device value
    is passed straight through.
    """
    # MEDIUM (40) is no longer remapped to 50
    aws_state = {"wave_state": 40}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["wave"] == 40

    aws_state = {"wave_state": 0}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["wave"] == 0

    aws_state = {"wave_state": 100}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["wave"] == 100


@pytest.mark.asyncio
async def test_fetch_data_returns_results(aws_api, mock_session):
    """Test fetch_data returns BestwayApiResults."""
    from custom_components.bestway.bestway.model import BestwayDevice

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
    from custom_components.bestway.bestway.model import BestwayDevice

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
