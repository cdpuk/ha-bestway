"""Structural interface shared by the Bestway cloud backends."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .model import BestwayApiResults, BestwayDevice, BubblesLevel


@runtime_checkable
class BackendApi(Protocol):
    """The surface BestwayUpdateCoordinator and the entity layer rely on.

    Backend-specific concerns are deliberately out of scope: the static login
    methods, set_device_state, and websocket wiring (which lives on the coordinator).
    """

    # Populated by refresh_bindings(); entities read it via coordinator.api.devices.
    devices: dict[str, BestwayDevice]

    # True only where the device's *own* connectivity report is part of the
    # state this backend returns (SmartSpa puts the shadow's `ConnectType` in
    # DeviceStatus.is_online). There an explicit "offline" means the spa is
    # reachable by the cloud but not by us - a spa that lost power keeps being
    # served from the cloud's cached shadow - so entities must show themselves
    # unavailable rather than keep their last known values.
    #
    # False everywhere else, because those flags are not a device heartbeat:
    # Gizwits' `is_online` reports working devices as offline (#89, #93, #100)
    # and the AWS IoT device record defaults it to True when absent.
    reports_device_heartbeat: bool

    async def refresh_bindings(self) -> None: ...
    async def fetch_data(self) -> BestwayApiResults: ...

    def handle_partial_update(
        self, device_id: str, attrs: dict[str, Any]
    ) -> BestwayApiResults:
        """Merge a partial WebSocket delta into backend state and return
        freshly translated results. The raw-state merge substrate is shared
        by all three backends (see raw_state.RawStateApi); this is the only
        mutation the coordinator performs through the protocol rather than
        reaching into backend internals.
        """
        ...

    # Semantic setters: one method per feature, device/backend-agnostic.
    # Each backend picks its own wire encoding internally based on the
    # target device's type. Raise NotImplementedError for a feature the
    # device/backend combination doesn't support - never silently no-op.
    async def set_power(self, device_id: str, power: bool) -> None: ...
    async def set_filter(self, device_id: str, filtering: bool) -> None: ...
    async def set_heat(self, device_id: str, heat: bool) -> None: ...
    async def set_locked(self, device_id: str, locked: bool) -> None: ...
    async def set_jets(self, device_id: str, jets: bool) -> None: ...
    async def set_target_temperature(
        self, device_id: str, temperature: int
    ) -> None: ...
    async def set_bubbles(self, device_id: str, bubbles: BubblesLevel) -> None: ...
    async def set_pool_timer(self, device_id: str, hours: int) -> None: ...
