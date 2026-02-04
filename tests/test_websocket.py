"""Tests for the Gizwits WebSocket module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions

from custom_components.bestway.bestway.websocket import (
    GizwitsWebSocket,
)


@pytest.mark.asyncio
async def test_websocket_connect_success():
    """Test successful WebSocket connection and authentication."""
    update_callback = MagicMock()
    disconnect_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="test_uid_123",
        token="test_token_abc",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
        disconnect_callback=disconnect_callback,
    )

    # Should not be connected initially
    assert not ws.is_connected

    with patch(
        "custom_components.bestway.bestway.websocket.websockets.connect"
    ) as mock_connect:
        with patch("homeassistant.util.ssl.get_default_context") as mock_ssl:
            with patch("asyncio.create_task"):
                mock_ws = MagicMock()
                mock_ws.send = AsyncMock()
                mock_ws.close = AsyncMock()
                mock_ssl.return_value = MagicMock()

                # Make connect return coroutine
                async def mock_connect_coro(*args, **kwargs):
                    return mock_ws

                mock_connect.side_effect = mock_connect_coro

                # Mock successful login response
                mock_ws.recv = AsyncMock(
                    return_value=json.dumps(
                        {"cmd": "login_res", "data": {"success": True}}
                    )
                )

                await ws.connect()

                # Verify connection established
                assert ws._running is True
                assert ws._authenticated is True
                assert ws._reconnect_count == 0

                # Verify connection called with correct URL
                mock_connect.assert_called_once()
                call_args = mock_connect.call_args[0]
                assert call_args[0] == "wss://m2m.gizwits.com:8880/ws/app/v1"

                # Verify login message sent
                mock_ws.send.assert_called_once()
                login_msg = json.loads(mock_ws.send.call_args[0][0])
                assert login_msg["cmd"] == "login_req"
                assert login_msg["data"]["uid"] == "test_uid_123"
                assert login_msg["data"]["token"] == "test_token_abc"
                assert login_msg["data"]["auto_subscribe"] is True

                # Verify background tasks created
                assert ws.is_connected

                # Cleanup
                ws._running = False
                await ws.disconnect()


@pytest.mark.asyncio
async def test_websocket_login_failure():
    """Test authentication failure handling."""
    update_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="bad_uid",
        token="bad_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    with patch(
        "custom_components.bestway.bestway.websocket.websockets.connect"
    ) as mock_connect:
        with patch("homeassistant.util.ssl.get_default_context") as mock_ssl:
            with patch("asyncio.create_task"):
                # Stop reconnection from actually happening
                with patch.object(ws, "_schedule_reconnect", new=AsyncMock()):
                    mock_ws = MagicMock()
                    mock_ws.send = AsyncMock()
                    mock_ws.close = AsyncMock()
                    mock_ssl.return_value = MagicMock()

                    async def mock_connect_coro(*args, **kwargs):
                        return mock_ws

                    mock_connect.side_effect = mock_connect_coro

                    # Mock failed login response
                    mock_ws.recv = AsyncMock(
                        return_value=json.dumps(
                            {
                                "cmd": "login_res",
                                "data": {
                                    "success": False,
                                    "msg": "Invalid credentials",
                                },
                            }
                        )
                    )

                    await ws.connect()

                    # Should not be authenticated
                    assert not ws.is_connected
                    assert not ws._authenticated
                    # Should have attempted to schedule reconnection
                    ws._schedule_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_device_update():
    """Test device update message handling."""
    updates_received = []

    def update_callback(device_id, attrs):
        updates_received.append((device_id, attrs))

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    # Test the message handler directly
    device_update_msg = {
        "cmd": "s2c_noti",
        "data": {
            "did": "device_abc123",
            "attrs": {
                "power": 1,
                "temp_now": 36,
                "temp_set": 38,
                "heat_power": 1,
                "filter_power": 1,
            },
        },
    }

    ws._handle_device_update(device_update_msg)

    # Verify callback was invoked
    assert len(updates_received) == 1
    assert updates_received[0][0] == "device_abc123"
    assert updates_received[0][1]["power"] == 1
    assert updates_received[0][1]["temp_now"] == 36


@pytest.mark.asyncio
async def test_websocket_device_update_empty_attrs():
    """Test device update with empty attributes."""
    update_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    # Device update with empty attrs
    device_update_msg = {"cmd": "s2c_noti", "data": {"did": "device_123", "attrs": {}}}

    ws._handle_device_update(device_update_msg)

    # Callback should not be invoked for empty attrs
    update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_device_update_missing_device_id():
    """Test device update without device ID."""
    update_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    # Device update without did
    device_update_msg = {"cmd": "s2c_noti", "data": {"attrs": {"power": 1}}}

    ws._handle_device_update(device_update_msg)

    # Callback should not be invoked
    update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_callback_exception_handling():
    """Test that exceptions in callback don't crash WebSocket."""

    def failing_callback(device_id, attrs):
        raise Exception("Callback error")

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=failing_callback,
    )

    # Should not raise exception
    device_update_msg = {
        "cmd": "s2c_noti",
        "data": {"did": "device_123", "attrs": {"power": 1}},
    }

    ws._handle_device_update(device_update_msg)
    # Test passes if no exception raised


@pytest.mark.asyncio
async def test_websocket_disconnect():
    """Test graceful disconnection."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    with patch(
        "custom_components.bestway.bestway.websocket.websockets.connect"
    ) as mock_connect:
        with patch("homeassistant.util.ssl.get_default_context"):
            with patch("asyncio.create_task"):
                mock_ws = MagicMock()
                mock_ws.send = AsyncMock()
                mock_ws.close = AsyncMock()

                async def mock_connect_coro(*args, **kwargs):
                    return mock_ws

                mock_connect.side_effect = mock_connect_coro

                # Mock successful login
                mock_ws.recv = AsyncMock(
                    return_value=json.dumps(
                        {"cmd": "login_res", "data": {"success": True}}
                    )
                )

                await ws.connect()

                # Verify connected
                assert ws.is_connected

                # Disconnect
                await ws.disconnect()

                # Verify disconnected
                assert not ws.is_connected
                mock_ws.close.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_already_running():
    """Test connect() when WebSocket already running."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    with patch(
        "custom_components.bestway.bestway.websocket.websockets.connect"
    ) as mock_connect:
        with patch("homeassistant.util.ssl.get_default_context"):
            with patch("asyncio.create_task"):
                mock_ws = MagicMock()
                mock_ws.send = AsyncMock()
                mock_ws.close = AsyncMock()

                async def mock_connect_coro(*args, **kwargs):
                    return mock_ws

                mock_connect.side_effect = mock_connect_coro

                mock_ws.recv = AsyncMock(
                    return_value=json.dumps(
                        {"cmd": "login_res", "data": {"success": True}}
                    )
                )

                await ws.connect()

                # Try to connect again
                await ws.connect()

                # Should only connect once (second call exits early)
                assert mock_connect.call_count == 1

                ws._running = False
                await ws.disconnect()


@pytest.mark.asyncio
async def test_websocket_connection_error():
    """Test connection failure handling."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    with patch(
        "custom_components.bestway.bestway.websocket.websockets.connect"
    ) as mock_connect:
        with patch("homeassistant.util.ssl.get_default_context"):
            # Stop reconnection from actually happening
            with patch.object(ws, "_schedule_reconnect", new=AsyncMock()):
                # Simulate connection error
                async def mock_connect_error(*args, **kwargs):
                    raise Exception("Connection refused")

                mock_connect.side_effect = mock_connect_error

                # Attempt connection (should not raise, should schedule reconnect)
                await ws.connect()

                # Should not be connected
                assert not ws.is_connected
                # Should have called _schedule_reconnect
                ws._schedule_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_disconnect_callback():
    """Test disconnect callback is invoked on connection loss."""
    update_callback = MagicMock()
    disconnect_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
        disconnect_callback=disconnect_callback,
    )

    # Test _handle_disconnect directly, stop reconnection
    with patch.object(ws, "_schedule_reconnect", new=AsyncMock()):
        await ws._handle_disconnect()

        # Verify disconnect callback invoked
        disconnect_callback.assert_called_once()

        # Verify state cleaned up
        assert not ws._running
        assert not ws._authenticated
        # Should have called _schedule_reconnect
        ws._schedule_reconnect.assert_called_once()


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_ping():
    """Test heartbeat loop sends ping messages."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    mock_ws = MagicMock()
    mock_ws.send = AsyncMock()
    ws._websocket = mock_ws
    ws._running = True

    # Test heartbeat sends ping
    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        # Run one iteration of heartbeat loop
        mock_sleep.side_effect = [
            None,
            asyncio.CancelledError(),
        ]  # First sleep succeeds, second cancels

        try:
            await ws._heartbeat_loop()
        except asyncio.CancelledError:
            pass

        # Verify ping was sent
        assert mock_ws.send.called
        ping_msg = json.loads(mock_ws.send.call_args[0][0])
        assert ping_msg["cmd"] == "ping"


@pytest.mark.asyncio
async def test_listen_loop_processes_messages():
    """Test listen loop processes incoming messages."""
    updates_received = []

    def update_callback(device_id, attrs):
        updates_received.append((device_id, attrs))

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    # Mock WebSocket with messages
    mock_ws = MagicMock()
    ws._websocket = mock_ws
    ws._running = False  # Set to False to prevent _handle_disconnect in finally

    # Create async iterator that yields messages then stops
    messages = [
        json.dumps(
            {"cmd": "s2c_noti", "data": {"did": "device1", "attrs": {"power": 1}}}
        ),
        json.dumps({"cmd": "pong"}),
        json.dumps(
            {"cmd": "s2c_online_status", "data": {"did": "device1", "is_online": True}}
        ),
    ]

    async def mock_async_iter():
        for msg in messages:
            yield msg

    mock_ws.__aiter__ = lambda self: mock_async_iter()

    # Run listen loop (will process messages then exit)
    await ws._listen_loop()

    # Verify device update was processed
    assert len(updates_received) == 1
    assert updates_received[0][0] == "device1"
    assert updates_received[0][1]["power"] == 1


@pytest.mark.asyncio
async def test_schedule_reconnect_exponential_backoff():
    """Test exponential backoff reconnection delays."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    # Mock sleep and connect to prevent actual delays/connections
    with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with patch.object(ws, "connect", new=AsyncMock()):
            # Test first reconnection (3 seconds)
            ws._reconnect_count = 0
            await ws._schedule_reconnect()
            mock_sleep.assert_called_with(3)
            assert ws._reconnect_count == 1

            # Test second reconnection (6 seconds)
            mock_sleep.reset_mock()
            await ws._schedule_reconnect()
            mock_sleep.assert_called_with(6)
            assert ws._reconnect_count == 2

            # Test max delay (60 seconds)
            ws._reconnect_count = 10  # Way beyond array
            mock_sleep.reset_mock()
            await ws._schedule_reconnect()
            mock_sleep.assert_called_with(60)  # Should use max delay


@pytest.mark.asyncio
async def test_listen_loop_handles_json_decode_error():
    """Test listen loop handles malformed JSON gracefully."""
    update_callback = MagicMock()
    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
    )

    mock_ws = MagicMock()
    ws._websocket = mock_ws
    ws._running = False  # Prevent _handle_disconnect in finally

    # Send malformed JSON
    async def mock_async_iter():
        yield "{ invalid json }"

    mock_ws.__aiter__ = lambda self: mock_async_iter()

    # Should not raise exception
    await ws._listen_loop()

    # Callback should not have been called
    update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_listen_loop_handles_connection_closed():
    """Test listen loop handles ConnectionClosed exception."""
    update_callback = MagicMock()
    disconnect_callback = MagicMock()

    ws = GizwitsWebSocket(
        uid="test_uid",
        token="test_token",
        ws_host="m2m.gizwits.com",
        ws_port=8880,
        update_callback=update_callback,
        disconnect_callback=disconnect_callback,
    )

    mock_ws = MagicMock()
    ws._websocket = mock_ws
    ws._running = True

    # Simulate ConnectionClosed exception
    async def mock_async_iter():
        if False:
            yield
        raise websockets.exceptions.ConnectionClosed(None, None)

    mock_ws.__aiter__ = lambda self: mock_async_iter()

    # Mock _handle_disconnect to prevent reconnection
    with patch.object(ws, "_handle_disconnect", new=AsyncMock()):
        await ws._listen_loop()

        # Should have called _handle_disconnect
        ws._handle_disconnect.assert_called_once()
