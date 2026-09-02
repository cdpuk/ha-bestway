"""Shared reconnect/teardown machinery for the Gizwits and AWS IoT
real-time WebSocket clients.

Both clients reconnect on the same exponential backoff schedule and need
the same "notify the disconnect callback at most once per disconnected
period" behaviour, and both tear down the same way: cancel the listen and
heartbeat tasks, then close the socket. The connection handshake, message
format and heartbeat payload differ too much between the two wire
protocols to share, so this base only covers what's genuinely identical.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from logging import getLogger
from typing import Any

_LOGGER = getLogger(__name__)

# Reconnection delays (exponential backoff): 3s -> 6s -> 12s -> 24s -> 48s -> 60s max
RECONNECT_DELAYS = [3, 6, 12, 24, 48, 60]

# Time to allow for TCP connect + TLS + opening handshake before giving up.
# Without this, a firewall that silently drops packets (rather than refusing
# the connection) leaves connect() hanging on the OS-level TCP timeout.
OPEN_TIMEOUT = 10


class BaseWebSocketClient:
    """Shared state, teardown and notification logic for a reconnecting
    WebSocket client.

    Subclasses (GizwitsWebSocket, AwsIotWebSocket) own connect(), the
    listen loop and the heartbeat loop - everything specific to their wire
    protocol - and use the attributes and helpers defined here:
    `_websocket`, `_listen_task`, `_heartbeat_task`, `_running`,
    `_reconnect_count`, `_notify_connected()`, `_notify_disconnected()`,
    `_cancel_and_close()`, `_next_reconnect_delay()`.
    """

    def __init__(
        self,
        disconnect_callback: Callable[[], None] | None = None,
        connect_callback: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the shared connection/backoff state."""
        self._disconnect_callback = disconnect_callback
        self._connect_callback = connect_callback

        self._websocket: Any = None
        self._listen_task: asyncio.Task[Any] | None = None
        self._heartbeat_task: asyncio.Task[Any] | None = None
        self._running = False
        self._reconnect_count = 0
        # Ensures disconnect_callback fires once per disconnected period,
        # rather than on every retry while backing off.
        self._notified_disconnect = False

    def _next_reconnect_delay(self) -> int:
        """Backoff delay for the current reconnect attempt.

        The index is clamped to the last entry, so the delay caps at
        RECONNECT_DELAYS[-1] (60s) rather than growing unbounded.
        """
        return RECONNECT_DELAYS[min(self._reconnect_count, len(RECONNECT_DELAYS) - 1)]

    async def _cancel_and_close(self) -> None:
        """Cancel the listen/heartbeat tasks and close the socket.

        Shared tail of disconnect() for both clients; subclasses handle
        their own flag/log bookkeeping before calling this.
        """
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

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as ex:
                _LOGGER.debug("Error closing WebSocket: %s", ex)
            finally:
                self._websocket = None

    def _notify_connected(self) -> None:
        """Invoke connect callback and re-arm the disconnect notification."""
        self._notified_disconnect = False
        if self._connect_callback:
            try:
                self._connect_callback()
            except Exception as ex:
                _LOGGER.error("Error in connect callback: %s", ex)

    def _notify_disconnected(self) -> None:
        """Invoke disconnect callback at most once per disconnected period.

        connect() is retried repeatedly while backing off, so without this
        guard a persistently unreachable endpoint would fire the callback
        (and its log warning) on every attempt.
        """
        if self._notified_disconnect:
            return
        self._notified_disconnect = True
        if self._disconnect_callback:
            try:
                self._disconnect_callback()
            except Exception as ex:
                _LOGGER.error("Error in disconnect callback: %s", ex)
