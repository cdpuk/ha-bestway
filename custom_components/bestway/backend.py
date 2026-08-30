"""Structural interface shared by the Bestway cloud backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .bestway.model import (
    BestwayDevice,
    BestwayDeviceStatus,
    BubblesLevel,
    HydrojetFilter,
    HydrojetHeat,
)

if TYPE_CHECKING:
    from .bestway.api import BestwayApiResults


@runtime_checkable
class BackendApi(Protocol):
    """The surface BestwayUpdateCoordinator and the entity layer rely on.

    Backend-specific concerns are deliberately out of scope: the static login
    methods, set_device_state, and websocket wiring (which lives on the coordinator).
    """

    # Populated by refresh_bindings(); entities read it via coordinator.api.devices.
    devices: dict[str, BestwayDevice]
    # Optimistic-state cache the coordinator merges websocket deltas into.
    _state_cache: dict[str, BestwayDeviceStatus]

    async def refresh_bindings(self) -> None: ...
    async def fetch_data(self) -> BestwayApiResults: ...

    async def airjet_spa_set_power(self, device_id: str, power: bool) -> None: ...
    async def airjet_spa_set_filter(self, device_id: str, filtering: bool) -> None: ...
    async def airjet_spa_set_heat(self, device_id: str, heat: bool) -> None: ...
    async def airjet_spa_set_target_temp(
        self, device_id: str, target_temp: int
    ) -> None: ...
    async def airjet_spa_set_locked(self, device_id: str, locked: bool) -> None: ...
    async def airjet_spa_set_bubbles(self, device_id: str, bubbles: bool) -> None: ...
    async def airjet_v01_spa_set_bubbles(
        self, device_id: str, bubbles: BubblesLevel
    ) -> None: ...

    async def hydrojet_spa_set_power(self, device_id: str, power: bool) -> None: ...
    async def hydrojet_spa_set_filter(
        self, device_id: str, filtering: HydrojetFilter
    ) -> None: ...
    async def hydrojet_spa_set_heat(
        self, device_id: str, heat: HydrojetHeat
    ) -> None: ...
    async def hydrojet_spa_set_target_temp(
        self, device_id: str, target_temp: int
    ) -> None: ...
    async def hydrojet_spa_set_bubbles(
        self, device_id: str, bubbles: BubblesLevel
    ) -> None: ...
    async def hydrojet_spa_set_jets(self, device_id: str, jets: bool) -> None: ...

    async def pool_filter_set_power(self, device_id: str, power: bool) -> None: ...
    async def pool_filter_set_time(self, device_id: str, hours: int) -> None: ...
