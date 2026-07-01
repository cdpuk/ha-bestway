"""Tests for AWS IoT API client."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.bestway.aws_iot.api import (
    AwsIotApi,
    AwsIotAuthException,
    AwsIotException,
    evaluate_convergence,
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
    """Test V02 wave_state value mapping to V01 format."""
    # V02 MEDIUM (40) maps to V01 Airjet MEDIUM (50)
    aws_state = {"wave_state": 40}
    normalized = AwsIotApi.normalize_aws_state(aws_state)
    assert normalized["wave"] == 50

    # 0 and 100 are the same in both versions
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


def _make_aws_device(device_id="device1"):
    """Build a real BestwayDevice for AWS IoT tests."""
    from custom_components.bestway.bestway.model import BestwayDevice

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
        backend="aws_iot",
        product_id="T53NN8",
    )


@pytest.mark.asyncio
async def test_fetch_data_raises_update_failed_when_all_devices_fail(aws_api):
    """A total poll failure surfaces as UpdateFailed so entities go unavailable."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    aws_api.devices = {"device1": _make_aws_device("device1")}
    aws_api._do_post = AsyncMock(side_effect=Exception("network down"))

    with pytest.raises(UpdateFailed):
        await aws_api.fetch_data()


@pytest.mark.asyncio
async def test_fetch_data_reauths_once_and_recovers(aws_api, monkeypatch):
    """An auth failure during a poll triggers one silent re-auth and recovers."""
    aws_api.devices = {"device1": _make_aws_device("device1")}

    shadow_ok = {"code": 0, "data": {"state": {"reported": {"power_state": 1}}}}
    # First poll auth-fails; after re-auth the retry succeeds.
    aws_api._do_post = AsyncMock(
        side_effect=[AwsIotAuthException("token expired"), shadow_ok]
    )
    monkeypatch.setattr(
        AwsIotApi, "authenticate", AsyncMock(return_value="fresh_token")
    )

    results = await aws_api.fetch_data()

    assert results.devices["device1"].attrs["power"] is True
    assert aws_api._token == "fresh_token"


@pytest.mark.asyncio
async def test_fetch_data_raises_auth_failed_when_reauth_fails(aws_api, monkeypatch):
    """If the re-authentication itself fails, raise ConfigEntryAuthFailed."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    aws_api.devices = {"device1": _make_aws_device("device1")}
    aws_api._do_post = AsyncMock(side_effect=AwsIotAuthException("token expired"))
    monkeypatch.setattr(
        AwsIotApi,
        "authenticate",
        AsyncMock(side_effect=AwsIotAuthException("bad visitor id")),
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await aws_api.fetch_data()


@pytest.mark.asyncio
async def test_fetch_data_no_devices_does_not_raise(aws_api):
    """With no devices configured, fetch_data must not raise."""
    aws_api.devices = {}
    results = await aws_api.fetch_data()
    assert hasattr(results, "devices")


# --- Fix B: command convergence verification ---------------------------------


def test_evaluate_convergence_truth_table():
    """Per-field convergence semantics: toggle=truthy, setpoint=exact."""
    # Toggle commanded ON but reported OFF -> non-converged.
    assert evaluate_convergence({"power_state": 1}, {"power_state": 0}) == {
        "power_state": 1
    }
    # Toggle commanded OFF and reported OFF -> converged.
    assert evaluate_convergence({"power_state": 0}, {"power_state": 0}) == {}
    # heater_state commanded ON, reported progress value 3 -> converged (truthy).
    assert evaluate_convergence({"heater_state": 1}, {"heater_state": 3}) == {}
    # heater_state commanded OFF but still reporting 3 -> non-converged.
    assert evaluate_convergence({"heater_state": 0}, {"heater_state": 3}) == {
        "heater_state": 0
    }
    # wave_state echo (commanded 100, device echoes 40) -> converged (truthy).
    assert evaluate_convergence({"wave_state": 100}, {"wave_state": 40}) == {}
    # Setpoint exact mismatch -> non-converged.
    assert evaluate_convergence(
        {"temperature_setting": 39}, {"temperature_setting": 20}
    ) == {"temperature_setting": 39}
    # Setpoint exact match (int echoed as float) -> converged.
    assert (
        evaluate_convergence({"temperature_setting": 39}, {"temperature_setting": 39.0})
        == {}
    )
    # Commanded field absent from reported shadow -> non-converged.
    assert evaluate_convergence({"power_state": 1}, {}) == {"power_state": 1}
    # Fully converged multi-field command -> empty.
    assert (
        evaluate_convergence(
            {"power_state": 1, "heater_state": 1},
            {"power_state": 1, "heater_state": 4},
        )
        == {}
    )


@pytest.mark.asyncio
async def test_set_device_state_notifies_verifier_on_success(aws_api, mock_session):
    """The command_verifier hook fires with the desired AWS fields on code:0."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    mock_session.post = MagicMock(return_value=create_mock_response(200, {"code": 0}))
    verifier = MagicMock()
    aws_api.command_verifier = verifier

    ok = await aws_api.set_device_state("device1", {"power_state": True})

    assert ok is True
    verifier.assert_called_once_with("device1", {"power_state": 1})


@pytest.mark.asyncio
async def test_set_device_state_no_verifier_on_failure(aws_api, mock_session):
    """The hook does NOT fire when both the v2 and v1 paths are rejected."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    mock_session.post = MagicMock(return_value=create_mock_response(200, {"code": 1}))
    aws_api._do_post = AsyncMock(return_value={"code": 1})  # v1 fallback also fails
    verifier = MagicMock()
    aws_api.command_verifier = verifier

    ok = await aws_api.set_device_state("device1", {"power_state": True})

    assert ok is False
    verifier.assert_not_called()


@pytest.mark.asyncio
async def test_set_device_state_notifies_verifier_on_v1_fallback(aws_api, mock_session):
    """The hook also fires when the v1 fallback path succeeds."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    mock_session.post = MagicMock(return_value=create_mock_response(200, {"code": 1}))
    aws_api._do_post = AsyncMock(return_value={"code": 0})  # v1 fallback succeeds
    verifier = MagicMock()
    aws_api.command_verifier = verifier

    ok = await aws_api.set_device_state("device1", {"temperature_setting": 39})

    assert ok is True
    verifier.assert_called_once_with("device1", {"temperature_setting": 39})


@pytest.mark.asyncio
async def test_fetch_reported_shadow_returns_raw_reported(aws_api):
    """_fetch_reported_shadow returns the untouched reported dict (AWS names)."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    aws_api._do_post = AsyncMock(
        return_value={
            "code": 0,
            "data": {"state": {"reported": {"power_state": 0, "heater_state": 3}}},
        }
    )

    reported = await aws_api._fetch_reported_shadow("device1")

    assert reported == {"power_state": 0, "heater_state": 3}


@pytest.mark.asyncio
async def test_fetch_reported_shadow_empty_when_missing(aws_api):
    """A shadow with no reported section yields {} (treated as non-converged)."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    aws_api._do_post = AsyncMock(return_value={"code": 0, "data": {}})

    assert await aws_api._fetch_reported_shadow("device1") == {}


@pytest.mark.asyncio
async def test_fetch_reported_shadow_empty_on_error(aws_api):
    """A shadow fetch error yields {} rather than raising."""
    aws_api.devices = {"device1": _make_aws_device("device1")}
    aws_api._do_post = AsyncMock(side_effect=AwsIotException("boom"))

    assert await aws_api._fetch_reported_shadow("device1") == {}


@pytest.mark.asyncio
async def test_coordinator_convergence_warns_and_fires_event(hass, aws_api):
    """A non-converging device produces a warning AND a bus event for automations.

    Also proves the check runs on a config-entry-lifecycle-tied task that
    completes cleanly (no leaked task) under async_block_till_done.
    """
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_capture_events,
    )

    from custom_components.bestway.coordinator import BestwayUpdateCoordinator

    entry = MockConfigEntry(domain="bestway", data={"backend": "aws_iot"})
    entry.add_to_hass(hass)
    aws_api.devices = {"device1": _make_aws_device("device1")}

    coordinator = BestwayUpdateCoordinator(hass, entry, aws_api)

    # The API's post-command hook is wired to the coordinator.
    assert aws_api.command_verifier == coordinator._schedule_convergence_check

    # Reported shadow shows the device did NOT converge (still off).
    aws_api._do_post = AsyncMock(
        return_value={
            "code": 0,
            "data": {"state": {"reported": {"power_state": 0}}},
        }
    )
    events = async_capture_events(hass, "bestway_command_unconverged")

    with (
        patch("custom_components.bestway.coordinator.COMMAND_CONVERGENCE_DELAY_S", 0),
        patch("custom_components.bestway.coordinator._LOGGER") as mock_logger,
    ):
        coordinator._schedule_convergence_check("device1", {"power_state": 1})
        await hass.async_block_till_done()

    assert mock_logger.warning.called
    assert len(events) == 1
    assert events[0].data["device_id"] == "device1"
    assert "power_state" in events[0].data["unconverged"]


@pytest.mark.asyncio
async def test_coordinator_convergence_silent_when_converged(hass, aws_api):
    """A converging device produces no warning and no event."""
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,
        async_capture_events,
    )

    from custom_components.bestway.coordinator import BestwayUpdateCoordinator

    entry = MockConfigEntry(domain="bestway", data={"backend": "aws_iot"})
    entry.add_to_hass(hass)
    aws_api.devices = {"device1": _make_aws_device("device1")}
    coordinator = BestwayUpdateCoordinator(hass, entry, aws_api)

    # Reported shadow confirms the command (power on).
    aws_api._do_post = AsyncMock(
        return_value={
            "code": 0,
            "data": {"state": {"reported": {"power_state": 1}}},
        }
    )
    events = async_capture_events(hass, "bestway_command_unconverged")

    with (
        patch("custom_components.bestway.coordinator.COMMAND_CONVERGENCE_DELAY_S", 0),
        patch("custom_components.bestway.coordinator._LOGGER") as mock_logger,
    ):
        coordinator._schedule_convergence_check("device1", {"power_state": 1})
        await hass.async_block_till_done()

    assert not mock_logger.warning.called
    assert len(events) == 0
