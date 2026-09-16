"""Raw-state merge substrate shared by every backend.

Each backend receives state from its cloud API faster than the API reflects
writes back: a POST that changes a setting isn't always visible in the very
next GET, and a WebSocket delta only ever carries a partial update. Every
backend therefore keeps a cache of the last-known wire attrs per device
(`RawSnapshot`) and merges new data into it - polled snapshots or partial
deltas alike - before translating the result into the typed `DeviceStatus`
entities read. That merge-and-translate logic doesn't vary by backend, so
it lives here once instead of being copied into each API class.

Backends still own everything upstream of this: how they poll
(`fetch_data`), how they discover devices (`refresh_bindings`), and how
they encode writes. Only the cache and its translation are shared.
"""

from __future__ import annotations

from time import time
from typing import Any

from .model import BestwayApiResults, BestwayDevice, BestwayDeviceType, RawSnapshot
from .translation import status_from_attrs

# refresh_bindings() runs on every coordinator poll, but the device list only
# changes when a device is added, removed or renamed in the Bestway app.
# Re-discovering it at most this often picks such a change up without hitting
# the device-list endpoints every poll.
DEVICE_REDISCOVERY_INTERVAL_S = 900


class RawStateApi:
    """Base class providing the raw-state cache shared by every backend.

    Concrete backends (`BestwayApi`, `AwsIotApi`, `SmartSpaApi`) inherit
    this for `devices`, `_raw_state`, `_results()` and
    `handle_partial_update()`. `handle_partial_update` is the only mutation
    the coordinator performs through the `BackendApi` protocol rather than
    reaching into backend internals.

    `devices` is populated by each backend's `refresh_bindings()`, which all
    three throttle through `_bindings_are_stale()` so the list ages out the
    same way on every backend.
    """

    def __init__(self) -> None:
        """Initialize the empty device registry and raw-state cache."""
        # Populated by refresh_bindings(); entities read it via coordinator.api.devices.
        self.devices: dict[str, BestwayDevice] = {}
        self._raw_state: dict[str, RawSnapshot] = {}
        self._bindings_refreshed_at: float | None = None

    def _bindings_are_stale(self) -> bool:
        """True when the cached device list is due for a re-discovery.

        An empty list always counts as stale, so the first poll discovers, and
        a discovery that failed or came back empty is retried on the next one.
        """
        if not self.devices or self._bindings_refreshed_at is None:
            return True
        return (time() - self._bindings_refreshed_at) >= DEVICE_REDISCOVERY_INTERVAL_S

    def _mark_bindings_refreshed(self) -> None:
        """Stamp the device list as freshly discovered."""
        self._bindings_refreshed_at = time()

    def _results(self) -> BestwayApiResults:
        """Translate the raw state cache into typed results.

        A raw entry with no matching device (e.g. a WebSocket delta that
        arrives before refresh_bindings() has run) translates against
        UNKNOWN rather than being dropped, so it still surfaces as a status
        with raw attrs even though no entity can be attached to it yet.
        """
        return BestwayApiResults(
            devices={
                device_id: status_from_attrs(
                    self.devices[device_id].device_type
                    if device_id in self.devices
                    else BestwayDeviceType.UNKNOWN,
                    snapshot.timestamp,
                    snapshot.attrs,
                )
                for device_id, snapshot in self._raw_state.items()
            }
        )

    def handle_partial_update(
        self, device_id: str, attrs: dict[str, Any]
    ) -> BestwayApiResults:
        """Merge a partial delta into the raw state cache and return freshly
        translated results.
        """
        existing = self._raw_state.get(device_id)
        merged = {**existing.attrs, **attrs} if existing else dict(attrs)
        self._raw_state[device_id] = RawSnapshot(int(time()), merged)
        return self._results()
