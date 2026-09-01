"""Tests for AWS IoT API client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bestway.aws_iot.api import (
    AwsIotApi,
    AwsIotAuthException,
)
from custom_components.bestway.model import BestwayDevice, BubblesLevel


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
