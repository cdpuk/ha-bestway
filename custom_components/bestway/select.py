"""Select platform."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.bestway.bestway.api import BestwayApi

from . import BestwayUpdateCoordinator
from .bestway.model import (
    AIRJET_V01_BUBBLES_MAP,
    HYDROJET_BUBBLES_MAP,
    BestwayDeviceType,
    BubblesLevel,
)
from .const import DOMAIN, Icon
from .entity import BestwayEntity

_BUBBLES_OPTIONS = {
    BubblesLevel.OFF: "OFF",
    BubblesLevel.MEDIUM: "MEDIUM",
    BubblesLevel.MAX: "MAX",
}


@dataclass(frozen=True)
class BubblesRequiredKeys:
    """Mixin for required keys."""

    set_fn: Callable[[BestwayApi, str, BubblesLevel], Awaitable[None]]
    get_fn: Callable[[int], BubblesLevel]


@dataclass(frozen=True)
class BubblesSelectEntityDescription(SelectEntityDescription, BubblesRequiredKeys):
    """Describes bubbles selection."""


_AIRJET_V01_BUBBLES_SELECT_DESCRIPTION = BubblesSelectEntityDescription(
    key="bubbles",
    options=list(_BUBBLES_OPTIONS.values()),
    icon=Icon.BUBBLES,
    name="Spa Bubbles",
    set_fn=lambda api, device_id, level: api.airjet_v01_spa_set_bubbles(
        device_id, level
    ),
    get_fn=lambda api_value: AIRJET_V01_BUBBLES_MAP.from_api_value(api_value),
)

_HYDROJET_BUBBLES_SELECT_DESCRIPTION = BubblesSelectEntityDescription(
    key="bubbles",
    options=list(_BUBBLES_OPTIONS.values()),
    icon=Icon.BUBBLES,
    name="Spa Bubbles",
    set_fn=lambda api, device_id, level: api.hydrojet_spa_set_bubbles(device_id, level),
    get_fn=lambda api_value: HYDROJET_BUBBLES_MAP.from_api_value(api_value),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        if device.device_type == BestwayDeviceType.AIRJET_V01_SPA:
            entities.append(
                ThreeWaySpaBubblesSelect(
                    coordinator,
                    config_entry,
                    device_id,
                    _AIRJET_V01_BUBBLES_SELECT_DESCRIPTION,
                )
            )

        if device.device_type in [
            BestwayDeviceType.HYDROJET_SPA,
            BestwayDeviceType.HYDROJET_PRO,
        ]:
            entities.append(
                ThreeWaySpaBubblesSelect(
                    coordinator,
                    config_entry,
                    device_id,
                    _HYDROJET_BUBBLES_SELECT_DESCRIPTION,
                )
            )

    async_add_entities(entities)


class ThreeWaySpaBubblesSelect(BestwayEntity, SelectEntity):
    """Bubbles selection for spa devices that support 3 levels."""

    entity_description: BubblesSelectEntityDescription

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: BubblesSelectEntityDescription,
    ) -> None:
        """Initialize thermostat."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        if device := self.coordinator.data.devices.get(self.device_id):
            bubbles_level = self.entity_description.get_fn(device.attrs["wave"])
            return _BUBBLES_OPTIONS.get(bubbles_level)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        bubbles_level = BubblesLevel.OFF
        if option == _BUBBLES_OPTIONS[BubblesLevel.MEDIUM]:
            bubbles_level = BubblesLevel.MEDIUM
        elif option == _BUBBLES_OPTIONS[BubblesLevel.MAX]:
            bubbles_level = BubblesLevel.MAX

        await self.entity_description.set_fn(
            self.coordinator.api, self.device_id, bubbles_level
        )
