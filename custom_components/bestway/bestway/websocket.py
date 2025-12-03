"""Gizwits WebSocket client for real-time device updates."""

import asyncio
import json
from logging import getLogger
from typing import Any, Callable

import websockets

from ..const import GIZWITS_APP_ID

_LOGGER = getLogger(__name__)

# Reconnection delays (exponential backoff): 3s → 6s → 12s → 24s → 48s → 60s max
_RECONNECT_DELAYS = [3, 6, 12, 24, 48, 60]


class GizwitsWebSocketException(Exception):
    """Base exception for WebSocket operations."""


class GizwitsWebSocket:
    """Gizwits WebSocket client for real-time device updates.

    Connects to Gizwits IoT platform WebSocket API to receive real-time
    device status updates via push notifications. Implements automatic
    reconnection with exponential backoff and graceful error handling.

    The WebSocket URL and port are extracted from the device bindings API
    response, allowing regional endpoint support without hardcoding.
    """

    def __init__(
        self,
        uid: str,
        token: str,
        ws_host: str,
        ws_port: int,
        update_callback: Callable[[str, dict[str, Any]], None],
        disconnect_callback: Callable[[], None] | None = None,
    ) -> None:
        """Initialize WebSocket client.

        Args:
            uid: User ID from Gizwits login API
            token: User token from Gizwits login API
            ws_host: WebSocket hostname (from device bindings response)
            ws_port: WebSocket port (from device bindings response)
            update_callback: Called with (device_id, attrs) on device updates
            disconnect_callback: Called on connection loss (optional)
        """
        self._uid = uid
        self._token = token
        self._ws_url = f"wss://{ws_host}:{ws_port}/ws/app/v1"
        self._update_callback = update_callback
        self._disconnect_callback = disconnect_callback

        self._websocket: Any = None
        self._listen_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._running = False
        self._authenticated = False
        self._reconnect_count = 0

    async def connect(self) -> None:
        """Connect to WebSocket and authenticate.

        Establishes SSL connection to Gizwits WebSocket API, sends login
        message with user credentials, and starts listening for device updates.

        Raises:
            GizwitsWebSocketException: If connection or authentication fails
        """
        if self._running:
            _LOGGER.warning("WebSocket already running")
            return

        _LOGGER.info("Connecting to Gizwits WebSocket: %s", self._ws_url)

        try:
            # Use Home Assistant's pre-cached SSL context (avoids blocking warnings)
            # Import here to avoid circular dependency
            from homeassistant.util import ssl as ssl_util

            ssl_context = ssl_util.get_default_context()

            # Connect with SSL (Gizwits requires secure connection)
            self._websocket = await websockets.connect(
                self._ws_url,
                ssl=ssl_context,
                ping_interval=30,  # Keep connection alive
                ping_timeout=10,
            )

            _LOGGER.debug("WebSocket connected, sending login")

            # Send login message
            await self._send_login()

            # Wait for login response with timeout
            if self._websocket is not None:
                response = await asyncio.wait_for(self._websocket.recv(), timeout=10)
            else:
                raise GizwitsWebSocketException("WebSocket not connected")

            data = json.loads(response)
            if data.get("cmd") != "login_res":
                raise GizwitsWebSocketException(
                    f"Expected login_res, got: {data.get('cmd')}"
                )

            if not data.get("data", {}).get("success"):
                error_msg = data.get("data", {}).get("msg", "Unknown error")
                raise GizwitsWebSocketException(f"Login failed: {error_msg}")

            self._authenticated = True
            self._running = True
            self._reconnect_count = 0  # Reset on successful connection

            _LOGGER.info("WebSocket authenticated successfully")

            # Start listening for messages and heartbeat
            self._listen_task = asyncio.create_task(self._listen_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as ex:
            _LOGGER.error("Failed to connect to WebSocket: %s", ex)
            await self.disconnect()

            # Schedule reconnection if still intended to be running
            if not isinstance(ex, asyncio.CancelledError):
                await self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources.

        Cancels background tasks and closes the WebSocket connection gracefully.
        Safe to call multiple times.
        """
        _LOGGER.debug("Disconnecting WebSocket")
        self._running = False
        self._authenticated = False

        # Cancel background tasks
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket connection
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as ex:
                _LOGGER.debug("Error closing WebSocket: %s", ex)
            finally:
                self._websocket = None

    async def _send_login(self) -> None:
        """Send login message to authenticate WebSocket connection.

        Uses Gizwits' login_req protocol with auto_subscribe enabled to
        automatically receive updates for all bound devices.
        """
        login_msg = {
            "cmd": "login_req",
            "data": {
                "appid": GIZWITS_APP_ID,
                "uid": self._uid,
                "token": self._token,
                "p0_type": "attrs_v4",  # Use attributes protocol
                "heartbeat_interval": 180,  # Send heartbeat every 180 seconds
                "auto_subscribe": True,  # Subscribe to all bound devices
            },
        }

        if self._websocket is not None:
            await self._websocket.send(json.dumps(login_msg))
            _LOGGER.debug("Login message sent")

    async def _heartbeat_loop(self) -> None:
        """Send application-level heartbeat to keep connection alive.

        Gizwits requires explicit ping/pong messages every 180 seconds
        to maintain the connection. This is separate from WebSocket
        protocol-level ping/pong frames.
        """
        while self._running:
            try:
                await asyncio.sleep(180)  # Wait 3 minutes

                if self._running and self._websocket is not None:
                    # Send application-level ping
                    await self._websocket.send(json.dumps({"cmd": "ping"}))
                    _LOGGER.debug("Heartbeat ping sent")

            except asyncio.CancelledError:
                break
            except Exception as ex:
                _LOGGER.warning("Heartbeat failed: %s", ex)
                # Don't break on heartbeat failure - let listen_loop detect connection issues
                break

    async def _listen_loop(self) -> None:
        """Listen for incoming WebSocket messages.

        Processes device update notifications and handles connection errors
        with automatic reconnection.
        """
        try:
            if self._websocket is None:
                return

            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    cmd = data.get("cmd")

                    _LOGGER.debug("Received message: cmd=%s", cmd)

                    if cmd == "s2c_noti":
                        # Device status update notification
                        self._handle_device_update(data)

                    elif cmd == "s2c_online_status":
                        # Device online/offline notification
                        device_data = data.get("data", {})
                        device_id = device_data.get("did")
                        is_online = device_data.get("is_online")
                        _LOGGER.info(
                            "Device %s is now %s",
                            device_id if device_id else "unknown",
                            "online" if is_online else "offline",
                        )

                    elif cmd == "s2c_invalid_msg":
                        # Invalid message error from server
                        _LOGGER.warning("Server reported invalid message: %s", data)

                    elif cmd == "pong":
                        # Heartbeat response
                        _LOGGER.debug("Heartbeat pong received")

                except json.JSONDecodeError:
                    _LOGGER.error("Failed to decode WebSocket message")
                except Exception as ex:
                    _LOGGER.error("Error processing WebSocket message: %s", ex)

        except websockets.exceptions.ConnectionClosed:
            _LOGGER.warning("WebSocket connection closed unexpectedly")
        except asyncio.CancelledError:
            _LOGGER.debug("WebSocket listen task cancelled")
        except Exception as ex:
            _LOGGER.error("WebSocket listen error: %s", ex)
        finally:
            if self._running:
                # Connection lost while we expected it to be running
                _LOGGER.warning("WebSocket connection lost, will attempt reconnect")
                await self._handle_disconnect()

    def _handle_device_update(self, data: dict[str, Any]) -> None:
        """Process device status update notification.

        Extracts device ID and attributes from s2c_noti message and
        invokes update callback.

        Args:
            data: Parsed JSON message with cmd='s2c_noti'
        """
        device_data = data.get("data", {})
        device_id = device_data.get("did")
        attrs = device_data.get("attrs", {})

        if not device_id:
            _LOGGER.warning("Received device update without device ID")
            return

        if not attrs:
            _LOGGER.debug("Received empty attrs for device %s", device_id)
            return

        _LOGGER.debug("Device update: %s with %d attributes", device_id, len(attrs))

        # Invoke update callback
        try:
            self._update_callback(device_id, attrs)
        except Exception as ex:
            _LOGGER.error("Error in update callback: %s", ex)

    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnection.

        Cleans up connection state and schedules reconnection attempt.
        """
        self._running = False
        self._authenticated = False

        # Notify disconnect callback
        if self._disconnect_callback:
            try:
                self._disconnect_callback()
            except Exception as ex:
                _LOGGER.error("Error in disconnect callback: %s", ex)

        # Schedule reconnection
        await self._schedule_reconnect()

    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection attempt with exponential backoff.

        Implements exponential backoff strategy:
        - Attempt 1: 3 seconds
        - Attempt 2: 6 seconds
        - Attempt 3: 12 seconds
        - Attempt 4: 24 seconds
        - Attempt 5: 48 seconds
        - Attempt 6+: 60 seconds (maximum delay)
        """
        # Determine delay based on reconnection attempt count
        if self._reconnect_count < len(_RECONNECT_DELAYS):
            delay = _RECONNECT_DELAYS[self._reconnect_count]
        else:
            delay = _RECONNECT_DELAYS[-1]  # Use maximum delay

        self._reconnect_count += 1

        _LOGGER.info(
            "Scheduling reconnection in %d seconds (attempt %d)",
            delay,
            self._reconnect_count,
        )

        # Wait for delay, then attempt reconnection
        await asyncio.sleep(delay)
        await self.connect()

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket is connected and authenticated.

        Returns:
            True if connection is active and login successful
        """
        return self._running and self._authenticated
