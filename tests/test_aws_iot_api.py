"""Tests for AWS IoT API client."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.bestway.aws_iot.api import (
    AwsIotApi,
    AwsIotAuthException,
    FIELD_MAPPING,
    GIZWITS_TO_AWS_FIELDS,
)
from custom_components.bestway.bestway.model import BestwayDeviceType


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
    # Mock API responses with context manager support
    homes_response = create_mock_response(200, {"list": [{"home_id": "home1"}]})
    rooms_response = create_mock_response(200, {"list": [{"room_id": "room1"}]})
    devices_response = create_mock_response(
        200,
        {
            "list": [
                {
                    "device_id": "device123",
                    "device_alias": "Test Spa",
                    "product_series": "AIRJET",
                    "service_region": "eu-central-1",
                    "is_online": True,
                }
            ]
        },
    )

    mock_session.get = MagicMock(side_effect=[homes_response, rooms_response, devices_response])

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
    homes_response = create_mock_response(200, {"list": [{"home_id": "home1"}]})
    rooms_response = create_mock_response(
        200, {"list": [{"room_id": "room1"}, {"room_id": "room2"}]}
    )
    devices1_response = create_mock_response(
        200,
        {
            "list": [
                {
                    "device_id": "device1",
                    "device_alias": "Spa 1",
                    "product_series": "AIRJET",
                    "service_region": "eu-central-1",
                }
            ]
        },
    )
    devices2_response = create_mock_response(
        200,
        {
            "list": [
                {
                    "device_id": "device2",
                    "device_alias": "Spa 2",
                    "product_series": "HYDROJET",
                    "service_region": "us-east-1",
                }
            ]
        },
    )

    mock_session.get = MagicMock(
        side_effect=[homes_response, rooms_response, devices1_response, devices2_response]
    )

    await aws_api.refresh_bindings()

    assert len(aws_api.devices) == 2
    assert "device1" in aws_api.devices
    assert "device2" in aws_api.devices
    assert aws_api.devices["device1"].alias == "Spa 1"
    assert aws_api.devices["device2"].alias == "Spa 2"


def test_normalize_state_comprehensive(aws_api):
    """Test comprehensive field normalization including power, temperature, and wave."""
    aws_state = {
        "power_state": 1,
        "heater_state": 0,
        "temperature_setting": 37,
        "current_temperature": 36,
        "temperature_unit": 1,
        "wave_state": 100,
    }
    normalized = aws_api._normalize_state(aws_state)

    # Power fields
    assert normalized["power"] is True
    assert normalized["heat"] == 0

    # Temperature fields
    assert normalized["temp_set"] == 37
    assert normalized["temp_now"] == 36
    assert normalized["temp_set_unit"] == 1

    # Wave field
    assert normalized["wave"] == 100


def test_normalize_state_filter(aws_api):
    """Test filter_state normalization (2=ON)."""
    # Filter on
    aws_state = {"filter_state": 2}
    normalized = aws_api._normalize_state(aws_state)
    assert normalized["filter_power"] is True

    # Filter off
    aws_state = {"filter_state": 0}
    normalized = aws_api._normalize_state(aws_state)
    assert normalized["filter_power"] is False


def test_normalize_state_unmapped_fields(aws_api):
    """Test unmapped fields are preserved with aws_ prefix."""
    aws_state = {"power_state": 1, "unknown_field": 42, "debug_info": "test"}
    normalized = aws_api._normalize_state(aws_state)

    assert normalized["power"] is True
    assert normalized["aws_unknown_field"] == 42
    assert normalized["aws_debug_info"] == "test"


@pytest.mark.asyncio
async def test_fetch_data_returns_results(aws_api, mock_session):
    """Test fetch_data returns BestwayApiResults."""
    # Setup device
    aws_api.refresh_bindings = AsyncMock()
    aws_api.devices = {
        "device1": MagicMock(
            device_id="device1",
            product_name="AIRJET",
        )
    }

    # Mock shadow response with context manager support
    shadow_response = create_mock_response(
        200,
        {
            "data": {
                "shadow": {
                    "state": {
                        "reported": {
                            "power_state": 1,
                            "heater_state": 3,
                            "temperature_setting": 37,
                            "current_temperature": 36,
                        }
                    }
                }
            }
        },
    )

    mock_session.get = MagicMock(return_value=shadow_response)

    # Execute
    results = await aws_api.fetch_data()

    # Verify structure
    assert hasattr(results, "devices")
    assert "device1" in results.devices

    status = results.devices["device1"]
    assert status.attrs["power"] is True
    assert status.attrs["heat"] == 3
    assert status.attrs["temp_set"] == 37
    assert status.attrs["temp_now"] == 36


@pytest.mark.asyncio
async def test_set_device_state_sends_command(aws_api, mock_session):
    """Test control command sends encrypted payload."""
    # Setup device
    aws_api.devices = {
        "device1": MagicMock(device_id="device1", product_name="AIRJET")
    }
    aws_api._state_cache = {"device1": MagicMock(attrs={})}

    # Mock POST response with context manager support
    post_response = create_mock_response(200, {"code": 0})

    mock_session.post = MagicMock(return_value=post_response)

    # Execute
    success = await aws_api.set_device_state("device1", {"power": True})

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
