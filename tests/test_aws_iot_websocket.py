"""Tests for AWS IoT WebSocket client."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.bestway.aws_iot.websocket import AwsIotWebSocket


@pytest.fixture
def mock_callback():
    """Create mock coordinator callback."""
    return MagicMock()


@pytest.fixture
def aws_websocket(mock_callback):
    """Create AwsIotWebSocket instance."""
    return AwsIotWebSocket(
        device_id="test_device_123",
        service_region="eu-central-1",
        token="test_token",
        update_callback=mock_callback,
    )


@pytest.mark.asyncio
async def test_connect_calls_websockets_with_auth_header(aws_websocket):
    """Test connect uses Authorization header."""
    with patch("websockets.connect") as mock_connect, \
         patch("homeassistant.util.ssl.get_default_context"), \
         patch.object(aws_websocket, "_listen_loop", return_value=None), \
         patch.object(aws_websocket, "_heartbeat_loop", return_value=None):

        mock_connect.return_value = AsyncMock()

        await aws_websocket.connect()

        # Verify Authorization header was passed
        call_kwargs = mock_connect.call_args.kwargs
        assert "additional_headers" in call_kwargs
        assert call_kwargs["additional_headers"]["Authorization"] == "test_token"
        assert aws_websocket._reconnect_count == 0


@pytest.mark.asyncio
async def test_handle_message_calls_callback_with_normalized_attrs(aws_websocket, mock_callback):
    """Test shadow delta message triggers callback with normalized fields."""
    # Shadow delta message from AWS IoT
    message = {
        "state": {
            "reported": {
                "power_state": 1,
                "heater_state": 3,
                "temperature_setting": 37,
            }
        }
    }

    with patch("custom_components.bestway.aws_iot.api.AwsIotApi.normalize_aws_state") as mock_normalize:
        mock_normalize.return_value = {"power": True, "heat": 3, "Tset": 37}

        await aws_websocket._handle_message(message)

        # Verify callback was called with device_id and normalized attrs
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0]
        assert call_args[0] == "test_device_123"  # device_id
        assert call_args[1] == {"power": True, "heat": 3, "Tset": 37}  # normalized


@pytest.mark.asyncio
async def test_handle_message_no_callback_error(aws_websocket):
    """Test message handling with missing callback doesn't crash."""
    aws_websocket._update_callback = None
    message = {"state": {"reported": {"power_state": 1}}}

    # Should not raise exception
    with patch("custom_components.bestway.aws_iot.api.AwsIotApi.normalize_aws_state"):
        await aws_websocket._handle_message(message)


@pytest.mark.asyncio
async def test_http_400_triggers_token_refresh(aws_websocket):
    """Test HTTP 400 error triggers token refresh and immediate retry."""
    token_refresh = AsyncMock(return_value="new_token_789")
    aws_websocket._token_refresh_callback = token_refresh

    with patch("custom_components.bestway.aws_iot.websocket.websockets.connect") as mock_connect:
        # First call fails with HTTP 400, second succeeds
        mock_connect.side_effect = [
            Exception("HTTP 400 Bad Request"),
            AsyncMock(),  # Success on second call
        ]

        await aws_websocket.connect()

        # Verify token refresh was called
        token_refresh.assert_called_once()
        assert aws_websocket._token == "new_token_789"
        # Should have retried (2 connect attempts)
        assert mock_connect.call_count == 2
        # Reconnect count should still be 0 (immediate retry, no backoff)
        assert aws_websocket._reconnect_count == 0


@pytest.mark.asyncio
async def test_disconnect_stops_running(aws_websocket):
    """Test disconnect stops the running flag and closes WebSocket."""
    mock_ws = AsyncMock()
    aws_websocket._websocket = mock_ws
    aws_websocket._running = True
    # No tasks to avoid await complexity in tests

    await aws_websocket.disconnect()

    assert aws_websocket._running is False
    assert mock_ws.close.called
    assert aws_websocket._websocket is None


@pytest.mark.asyncio
async def test_reconnect_uses_exponential_backoff(aws_websocket):
    """Test reconnection delay increases with each attempt."""
    aws_websocket._running = True

    with patch("custom_components.bestway.aws_iot.websocket.asyncio.sleep") as mock_sleep, \
         patch.object(aws_websocket, "connect", new_callable=AsyncMock):

        # First reconnect (delay = 3s)
        aws_websocket._reconnect_count = 0
        await aws_websocket._schedule_reconnect()
        mock_sleep.assert_called_with(3)
        assert aws_websocket._reconnect_count == 1

        # Second reconnect (delay = 6s)
        await aws_websocket._schedule_reconnect()
        mock_sleep.assert_called_with(6)
        assert aws_websocket._reconnect_count == 2


@pytest.mark.asyncio
async def test_region_fallback_to_eu(aws_websocket):
    """Test unknown region falls back to EU endpoint."""
    aws_websocket._service_region = "unknown-region-99"

    url = aws_websocket.ws_url

    # Should use EU endpoint as fallback
    assert "eu-central-1" in url


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_messages(aws_websocket):
    """Test heartbeat loop sends JSON heartbeat and WebSocket ping."""
    mock_ws = MagicMock()
    mock_ws.send = AsyncMock()
    mock_ws.ping = AsyncMock()

    aws_websocket._websocket = mock_ws
    aws_websocket._running = True

    # Mock asyncio.sleep to run one iteration then cancel
    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        mock_sleep.side_effect = [None, asyncio.CancelledError()]

        try:
            await aws_websocket._heartbeat_loop()
        except asyncio.CancelledError:
            pass

        # Verify both heartbeat messages sent
        assert mock_ws.send.called
        assert mock_ws.ping.called

        # Verify JSON heartbeat format
        heartbeat_msg = json.loads(mock_ws.send.call_args[0][0])
        assert heartbeat_msg["action"] == "heartbeat"
        assert heartbeat_msg["req_event"] == "heartbeat_req"
        assert "seq_id" in heartbeat_msg


@pytest.mark.asyncio
async def test_listen_loop_processes_shadow_updates(aws_websocket):
    """Test listen loop processes incoming shadow delta messages."""
    updates_received = []

    def capture_callback(device_id, attrs):
        updates_received.append((device_id, attrs))

    aws_websocket._update_callback = capture_callback

    # Mock WebSocket to yield messages
    mock_ws = MagicMock()
    message1 = json.dumps({"state": {"reported": {"power_state": 1}}})
    message2 = json.dumps({"state": {"reported": {"heater_state": 3}}})

    async def message_generator():
        yield message1
        yield message2

    mock_ws.__aiter__ = lambda self: message_generator()
    aws_websocket._websocket = mock_ws

    with patch("custom_components.bestway.aws_iot.api.AwsIotApi.normalize_aws_state") as mock_normalize:
        mock_normalize.side_effect = [
            {"power": True},
            {"heat": 3},
        ]

        await aws_websocket._listen_loop()

        # Verify both messages processed
        assert len(updates_received) == 2
        assert updates_received[0] == ("test_device_123", {"power": True})
        assert updates_received[1] == ("test_device_123", {"heat": 3})


@pytest.mark.asyncio
async def test_connection_closed_triggers_reconnect(aws_websocket):
    """Test listen loop handles connection closure."""
    from websockets.exceptions import ConnectionClosed

    mock_ws = AsyncMock()
    mock_ws.__aiter__.return_value = iter([])  # Empty iterator

    aws_websocket._websocket = mock_ws
    aws_websocket._running = True

    with patch.object(aws_websocket, "_schedule_reconnect", new_callable=AsyncMock) as mock_reconnect:
        # Simulate connection closed by raising exception
        mock_ws.__aiter__.side_effect = ConnectionClosed(None, None)

        await aws_websocket._listen_loop()

        # Should have scheduled reconnect
        mock_reconnect.assert_called_once()
