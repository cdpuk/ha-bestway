"""Switch platform support."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .backend import BackendApi
from .const import DOMAIN, Icon
from .entity import BestwayEntity
from .features import BubblesStyle, DeviceKind, features_for
from .model import BubblesLevel, DeviceStatus

# Maximum time an optimistic value is trusted before the entity falls back
# to whatever the cloud last reported. Long enough to ride out a normal
# Bestway/AWS round trip, short enough that a stuck UI self-heals quickly
# when commands fail or get processed out of order.
_OPTIMISTIC_TIMEOUT_S = 8.0


@dataclass(frozen=True, kw_only=True)
class BestwaySwitchEntityDescription(SwitchEntityDescription):
    """Entity description for bestway spa switches."""

    value_fn: Callable[[DeviceStatus], bool]
    turn_on_fn: Callable[[BackendApi, str], Awaitable[None]]
    turn_off_fn: Callable[[BackendApi, str], Awaitable[None]]


_SPA_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_power",
    name="Spa Power",
    icon=Icon.POWER,
    value_fn=lambda s: bool(s.power),
    turn_on_fn=lambda api, device_id: api.set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.set_power(device_id, False),
)

_POOL_FILTER_POWER_SWITCH = BestwaySwitchEntityDescription(
    key="pool_filter_power",
    name="Pool Filter Power",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.power),
    turn_on_fn=lambda api, device_id: api.set_power(device_id, True),
    turn_off_fn=lambda api, device_id: api.set_power(device_id, False),
)

_SPA_FILTER_SWITCH = BestwaySwitchEntityDescription(
    key="spa_filter_power",
    name="Spa Filter",
    icon=Icon.FILTER,
    value_fn=lambda s: bool(s.filtering),
    turn_on_fn=lambda api, device_id: api.set_filter(device_id, True),
    turn_off_fn=lambda api, device_id: api.set_filter(device_id, False),
)

# One description serves every on/off bubbles device, binary-hardware
# devices included: any non-OFF level reads as "on", and the backend picks
# the write value per device type.
_SPA_BUBBLES_SWITCH = BestwaySwitchEntityDescription(
    key="spa_wave_power",
    name="Spa Bubbles",
    icon=Icon.BUBBLES,
    value_fn=lambda s: s.bubbles is not None and s.bubbles is not BubblesLevel.OFF,
    turn_on_fn=lambda api, device_id: api.set_bubbles(device_id, BubblesLevel.MAX),
    turn_off_fn=lambda api, device_id: api.set_bubbles(device_id, BubblesLevel.OFF),
)

_SPA_LOCK_SWITCH = BestwaySwitchEntityDescription(
    key="spa_locked",
    name="Spa Locked",
    icon=Icon.LOCK,
    value_fn=lambda s: bool(s.locked),
    turn_on_fn=lambda api, device_id: api.set_locked(device_id, True),
    turn_off_fn=lambda api, device_id: api.set_locked(device_id, False),
)

_SPA_JETS_SWITCH = BestwaySwitchEntityDescription(
    key="spa_jets",
    name="Spa Jets",
    icon=Icon.JETS,
    value_fn=lambda s: bool(s.jets),
    turn_on_fn=lambda api, device_id: api.set_jets(device_id, True),
    turn_off_fn=lambda api, device_id: api.set_jets(device_id, False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        features = features_for(device, config_entry.options)
        is_pool_filter = features.device_kind == DeviceKind.POOL_FILTER

        if features.power_switch:
            description = (
                _POOL_FILTER_POWER_SWITCH if is_pool_filter else _SPA_POWER_SWITCH
            )
            entities.append(
                BestwaySwitch(coordinator, config_entry, device_id, description)
            )

        if features.filter_switch:
            entities.append(
                BestwaySwitch(coordinator, config_entry, device_id, _SPA_FILTER_SWITCH)
            )

        if features.jets_switch:
            entities.append(
                BestwaySwitch(coordinator, config_entry, device_id, _SPA_JETS_SWITCH)
            )

        if features.lock_switch:
            entities.append(
                BestwaySwitch(coordinator, config_entry, device_id, _SPA_LOCK_SWITCH)
            )

        if features.bubbles == BubblesStyle.SWITCH:
            entities.append(
                BestwaySwitch(coordinator, config_entry, device_id, _SPA_BUBBLES_SWITCH)
            )

    async_add_entities(entities)


class BestwaySwitch(BestwayEntity, SwitchEntity):
    """Bestway switch entity."""

    entity_description: BestwaySwitchEntityDescription
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BestwaySwitchEntityDescription,
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._optimistic_state: bool | None = None
        self._optimistic_set_at: float = 0.0

    def _set_optimistic(self, value: bool) -> None:
        """Set the optimistic value and stamp it for the timeout check."""
        self._optimistic_state = value
        self._optimistic_set_at = monotonic()

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self._optimistic_state is not None:
            return self._optimistic_state
        if status := self.status:
            return self.entity_description.value_fn(status)

        return None

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state once real data confirms it, or after a
        short timeout.

        Without the confirmation check, a refresh that fires before the
        cloud has acked the command exposes the stale "old" state and the
        UI flickers ON -> OFF -> ON. Without the timeout, a rapid
        double-tap (or any command the cloud reorders / drops) can leave
        the switch stuck on the unconfirmed value indefinitely because
        the real state never matches.
        """
        if self._optimistic_state is not None and self.status is not None:
            actual = self.entity_description.value_fn(self.status)
            confirmed = actual == self._optimistic_state
            timed_out = monotonic() - self._optimistic_set_at >= _OPTIMISTIC_TIMEOUT_S
            if confirmed or timed_out:
                self._optimistic_state = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._set_optimistic(True)
        self.async_write_ha_state()
        await self.entity_description.turn_on_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._set_optimistic(False)
        self.async_write_ha_state()
        await self.entity_description.turn_off_fn(self.coordinator.api, self.device_id)
        await self.coordinator.async_request_refresh()
