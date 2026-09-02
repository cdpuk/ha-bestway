"""Home Assistant entity descriptions."""

from __future__ import annotations

from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BestwayUpdateCoordinator
from .model import BestwayDevice, DeviceStatus

# Maximum time an optimistic value is trusted before an entity falls back
# to whatever the cloud last reported. Long enough to ride out a normal
# Bestway/AWS round trip, short enough that a stuck UI self-heals quickly
# when a command fails or gets processed out of order.
OPTIMISTIC_TIMEOUT_S = 8.0


class OptimisticValue[T]:
    """A value written locally so an entity reflects a command immediately,
    rather than waiting for the next coordinator refresh to confirm it.

    Without the confirmation check in `confirm()`, a refresh that lands
    before the cloud has acked the command would flash the entity back to
    its pre-command state. Without the timeout, a command the cloud drops
    or reorders would leave the entity stuck showing an unconfirmed value
    forever. Entities call `set()` when they write a value optimistically,
    and `confirm()` from `_handle_coordinator_update()` with whatever the
    latest real data says.
    """

    def __init__(self, timeout_s: float = OPTIMISTIC_TIMEOUT_S) -> None:
        """Initialize with no optimistic value set."""
        self._timeout_s = timeout_s
        self._value: T | None = None
        self._set_at: float = 0.0

    @property
    def value(self) -> T | None:
        """The optimistic value, or None if there isn't one right now."""
        return self._value

    def set(self, value: T) -> None:
        """Record a value written locally, stamped for the timeout check."""
        self._value = value
        self._set_at = monotonic()

    def confirm(self, actual: T | None) -> None:
        """Clear the optimistic value once `actual` matches it, or once the
        timeout has elapsed - whichever comes first. A no-op if there is no
        optimistic value pending.
        """
        if self._value is None:
            return
        timed_out = monotonic() - self._set_at >= self._timeout_s
        if actual == self._value or timed_out:
            self._value = None


class BestwayEntity(CoordinatorEntity[BestwayUpdateCoordinator]):
    """Bestway base entity type."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.device_id = device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Device information for the spa providing this entity."""

        device = self.coordinator.api.devices[self.device_id]

        # Build model string like reference: "AIRJET (T53NN8)" or just device type
        if device.product_series and device.product_id:
            model = f"{device.product_series} ({device.product_id})"
        elif device.product_id:
            model = device.product_id
        elif device.product_series:
            model = device.product_series
        else:
            model = device.device_type.value

        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=device.alias,
            model=model,
            manufacturer="Bestway",
            sw_version=device.mcu_soft_version,  # Add version info
        )

    @property
    def bestway_device(self) -> BestwayDevice | None:
        """Get status data for the spa providing this entity."""
        device: BestwayDevice | None = self.coordinator.api.devices.get(self.device_id)
        return device

    @property
    def status(self) -> DeviceStatus | None:
        """Get status data for the spa providing this entity."""
        status: DeviceStatus | None = self.coordinator.data.devices.get(self.device_id)
        return status

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Note: is_online from the Bestway/Gizwits API is unreliable and
        frequently returns false even when the device is functioning and
        controllable via the app. The API continues to return valid state
        data regardless of this flag. We therefore only check that the
        coordinator has data and the device is known.

        See: https://github.com/cdpuk/ha-bestway/issues/89
        See: https://github.com/cdpuk/ha-bestway/issues/93
        See: https://github.com/cdpuk/ha-bestway/issues/100
        """
        return self.coordinator.last_update_success and self.bestway_device is not None
