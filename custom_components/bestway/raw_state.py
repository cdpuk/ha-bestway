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


class RawStateApi:
    """Base class providing the raw-state cache shared by every backend.

    Concrete backends (`BestwayApi`, `AwsIotApi`, `SmartSpaApi`) inherit
    this for `devices`, `_raw_state`, `_results()` and
    `handle_partial_update()`. `handle_partial_update` is the only mutation
    the coordinator performs through the `BackendApi` protocol rather than
    reaching into backend internals.
    """

    def __init__(self) -> None:
        """Initialize the empty device registry and raw-state cache."""
        # Populated by refresh_bindings(); entities read it via coordinator.api.devices.
        self.devices: dict[str, BestwayDevice] = {}
        self._raw_state: dict[str, RawSnapshot] = {}

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
