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

    Subclasses (GizwitsWebSocket, AwsIotWebSocket) own `_connect_once()`, the
    listen loop and the heartbeat loop - everything specific to their wire
    protocol - and use the attributes and helpers defined here:
    `_websocket`, `_listen_task`, `_heartbeat_task`, `_running`,
    `_should_run`, `_reconnect_task`, `_reconnect_count`,
    `_notify_connected()`, `_notify_disconnected()`, `_handle_disconnect()`,
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
        # Whether the socket is live, versus whether we *want* it to be: a
        # reconnect is exactly the case where the first is False and the second
        # is True, so scheduling has to gate on the intent, not on _running.
        self._running = False
        self._should_run = False
        self._reconnect_task: asyncio.Task[Any] | None = None
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

    async def connect(self) -> None:
        """Connect, and keep retrying until disconnect() is called.

        Subclasses implement `_connect_once()`; the retry chain lives here so
        both clients share one flat loop instead of a call chain that grows
        with every attempt.
        """
        self._should_run = True
        await self._connect_once()

        if not self._running:
            await self._schedule_reconnect()

    async def _connect_once(self) -> None:
        """Open one connection and start its tasks; subclass hook.

        Reports a failed attempt by leaving `_running` False - it must not
        schedule its own retry, which is what `_schedule_reconnect()` is for.
        """

    async def _handle_disconnect(self) -> None:
        """React to a connection that dropped while we wanted it alive.

        Called from the listen loop (and the heartbeat loop), which must not
        become the retry driver itself: the retry path cancels the listen and
        heartbeat tasks first, which a task cannot do to itself and survive.
        So the reconnect runs in its own task, and this returns immediately.

        A no-op when the drop happened because something called disconnect():
        that is the only case where a lost socket must *not* be followed by a
        reconnect, and it is precisely what `_should_run` distinguishes.
        """
        if not self._should_run:
            return

        self._running = False
        self._notify_disconnected()

        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self.connect())

    async def _schedule_reconnect(self) -> None:
        """Keep retrying until connected again or told to stop.

        This loop owns every retry: each attempt returns to it, so the call
        stack stays flat no matter how long the endpoint stays unreachable. A
        chain of `connect()` calling itself would add a frame per attempt and
        eventually hit Python's recursion limit - after hours of downtime,
        which is exactly when a device is most likely to be offline.
        """
        while self._should_run:
            delay = self._next_reconnect_delay()
            self._reconnect_count += 1

            _LOGGER.info(
                "Reconnecting in %ds (attempt %d)", delay, self._reconnect_count
            )

            await asyncio.sleep(delay)

            await self._connect_once()

            if self._running:
                return

    async def _cancel_and_close(self) -> None:
        """Cancel the listen/heartbeat/reconnect tasks and close the socket.

        Shared tail of disconnect() for both clients; subclasses handle
        their own flag/log bookkeeping before calling this.
        """
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

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
