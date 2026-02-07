"""AWS IoT WebSocket client for V02 device real-time updates.

Provides near-instant state synchronization by connecting to regional AWS API Gateway
endpoints and receiving device shadow delta updates from AWS IoT Core.

Key differences from Gizwits WebSocket:
- No login message (Authorization header authentication)
- Per-device connection (one WebSocket per device)
- Regional endpoints (eu-central-1, us-west-1, etc)
- Shadow delta message format (not s2c_noti)
- 30s heartbeat (not 180s)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable
from typing import Any, Callable

import websockets
from websockets.asyncio.client import ClientConnection

_LOGGER = logging.getLogger(__name__)

# Regional WebSocket endpoints (from official app ServiceConfig.java)
ENDPOINTS = {
    "eu-central-1": "wss://7lv67j5lbh.execute-api.eu-central-1.amazonaws.com/prod",
    "us-west-1": "wss://9i661wi8f9.execute-api.us-west-1.amazonaws.com/prod",
    "cn-north-1": "wss://fu9gsv4dxh.execute-api.cn-north-1.amazonaws.com.cn/prod",
}

# Reconnection delays (exponential backoff)
RECONNECT_DELAYS = [3, 6, 12, 24, 48, 60]  # seconds


class AwsIotWebSocketException(Exception):
    """Base exception for AWS IoT WebSocket operations."""


class AwsIotWebSocket:
    """Per-device WebSocket client for AWS IoT shadow updates.

    Each device requires its own WebSocket connection to receive real-time
    state updates from AWS IoT device shadows. Implements automatic
    reconnection and integrates with coordinator callbacks.
    """

    def __init__(
        self,
        device_id: str,
        service_region: str,
        token: str,
        update_callback: Callable[[str, dict[str, Any]], None],
        disconnect_callback: Callable[[], None] | None = None,
        token_refresh_callback: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Initialize per-device WebSocket client.

        Args:
            device_id: Device ID for shadow subscription
            service_region: AWS region (e.g., "eu-central-1")
            token: JWT authentication token
            update_callback: Called with (device_id, normalized_attrs) on updates
            disconnect_callback: Called on connection loss (optional)
            token_refresh_callback: Called to refresh token on HTTP 400 (optional)
        """
        self._device_id = device_id
        self._service_region = service_region
        self._token = token
        self._update_callback = update_callback
        self._disconnect_callback = disconnect_callback
        self._token_refresh_callback = token_refresh_callback

        self._websocket: ClientConnection | None = None
        self._listen_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._running = False
        self._reconnect_count = 0
        self._seq_id = int(time.time() * 1000)

    @property
    def ws_url(self) -> str:
        """Get region-specific WebSocket endpoint."""
        endpoint = ENDPOINTS.get(self._service_region, ENDPOINTS["eu-central-1"])
        if self._service_region not in ENDPOINTS:
            _LOGGER.warning(
                "Unknown region %s for device %s, using EU",
                self._service_region,
                self._device_id[:12],
            )
        return endpoint

    async def connect(self) -> None:
        """Connect to region-specific WebSocket endpoint.

        Establishes connection to AWS API Gateway with Authorization header
        and starts background tasks for heartbeat and message listening.
        """
        if self._running:
            _LOGGER.warning(
                "WebSocket already running for device %s", self._device_id[:12]
            )
            return

        _LOGGER.info(
            "Connecting WebSocket for device %s (region: %s)",
            self._device_id[:12],
            self._service_region,
        )

        try:
            # Use Home Assistant's SSL context
            from homeassistant.util import ssl as ssl_util

            ssl_context = ssl_util.get_default_context()

            # Connect with Authorization header (no login message needed)
            self._websocket = await websockets.connect(
                self.ws_url,
                additional_headers={"Authorization": self._token},
                ssl=ssl_context,
                ping_interval=None,  # Manual heartbeat
            )

            self._running = True
            self._reconnect_count = 0  # Reset on successful connection

            _LOGGER.info("✓ WebSocket connected for device %s", self._device_id[:12])

            # Start background tasks
            self._listen_task = asyncio.create_task(self._listen_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as err:
            error_msg = str(err)
            _LOGGER.error(
                "WebSocket connection failed for device %s: %s",
                self._device_id[:12],
                error_msg,
            )

            # Handle HTTP 400 (token expired) - trigger refresh and immediate retry
            if "HTTP 400" in error_msg and self._token_refresh_callback is not None:
                _LOGGER.info("HTTP 400 detected - attempting token refresh")
                try:
                    new_token = await self._token_refresh_callback()
                    if new_token:
                        self._token = new_token
                        _LOGGER.info("Token refreshed, immediate retry")
                        # Immediate retry (don't increment reconnect count)
                        await self.connect()
                        return
                except Exception as refresh_err:
                    _LOGGER.error("Token refresh failed: %s", str(refresh_err))

            # Schedule reconnection with backoff
            if not isinstance(err, asyncio.CancelledError):
                await self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Disconnect and cleanup resources.

        Cancels background tasks and closes WebSocket connection gracefully.
        Safe to call multiple times.
        """
        _LOGGER.info("Disconnecting WebSocket for device %s", self._device_id[:12])
        self._running = False

        # Cancel listen task
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        # Cancel heartbeat task
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as ex:
                _LOGGER.debug("Error closing WebSocket: %s", ex)
            finally:
                self._websocket = None

        _LOGGER.info("✓ WebSocket disconnected for device %s", self._device_id[:12])

    async def _listen_loop(self) -> None:
        """Listen for incoming shadow update messages.

        Processes device shadow deltas and triggers coordinator callback
        with normalized attributes.
        """
        try:
            if self._websocket is None:
                return

            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)

                except json.JSONDecodeError:
                    _LOGGER.warning("Received malformed JSON message")

        except websockets.exceptions.ConnectionClosed:
            _LOGGER.warning("WebSocket closed for device %s", self._device_id[:12])
            # Trigger reconnection
            if self._running:
                await self._schedule_reconnect()

        except Exception as err:
            _LOGGER.error(
                "Listen loop error for device %s: %s", self._device_id[:12], err
            )
            if self._running:
                await self._schedule_reconnect()

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Process shadow delta message.

        Args:
            data: Parsed WebSocket message containing shadow state
        """
        # Extract shadow state (matches AWS IoT shadow delta format)
        if "state" in data and "reported" in data.get("state", {}):
            state = data["state"]["reported"]

            _LOGGER.debug(
                "Shadow update for device %s: %d fields",
                self._device_id[:12],
                len(state),
            )

            # Normalize AWS field names to Gizwits V01 equivalents using shared method
            from .api import AwsIotApi

            normalized = AwsIotApi.normalize_aws_state(state)

            # Call coordinator callback with (device_id, normalized_attrs)
            if self._update_callback is not None:
                try:
                    self._update_callback(self._device_id, normalized)
                except Exception as err:
                    _LOGGER.error("Callback error: %s", err)

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat every 30 seconds to maintain connection."""
        while self._running:
            try:
                await asyncio.sleep(30)

                if self._running and self._websocket:
                    # Send application-level heartbeat (JSON message)
                    message = {
                        "action": "heartbeat",
                        "req_event": "heartbeat_req",
                        "seq_id": self._seq_id,
                        "req_count": 1,
                        "req": None,
                    }
                    await self._websocket.send(json.dumps(message))

                    # Also send WebSocket protocol ping
                    await self._websocket.ping()

                    self._seq_id += 1
                    _LOGGER.debug("Heartbeat sent for device %s", self._device_id[:12])

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.warning(
                    "Heartbeat failed for device %s: %s", self._device_id[:12], err
                )
                break

    async def _schedule_reconnect(self) -> None:
        """Schedule reconnection with exponential backoff.

        Delays: 3s → 6s → 12s → 24s → 48s → 60s (max)
        """
        if not self._running:
            return

        # Get delay based on reconnect count
        delay_index = min(self._reconnect_count, len(RECONNECT_DELAYS) - 1)
        delay = RECONNECT_DELAYS[delay_index]

        _LOGGER.info(
            "Reconnecting device %s in %ds (attempt %d)",
            self._device_id[:12],
            delay,
            self._reconnect_count + 1,
        )

        # Increment for next attempt
        self._reconnect_count += 1

        # Wait and reconnect
        await asyncio.sleep(delay)

        if self._running:
            await self.connect()
