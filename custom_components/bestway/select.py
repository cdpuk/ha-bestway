"""Select platform."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .const import DOMAIN, Icon
from .entity import BestwayEntity
from .features import BubblesStyle, features_for
from .model import BubblesLevel

_BUBBLES_OPTIONS = {
    BubblesLevel.OFF: "OFF",
    BubblesLevel.MEDIUM: "MEDIUM",
    BubblesLevel.MAX: "MAX",
}

# The read/write map differences between Airjet and Hydrojet device types
# now live entirely in the backend (see bubbles_map_for() in
# bestway/translation.py); the entity just reads status.bubbles and writes
# via set_bubbles(), so one description serves both three-way styles.
_BUBBLES_SELECT_DESCRIPTION = SelectEntityDescription(
    key="bubbles",
    options=list(_BUBBLES_OPTIONS.values()),
    icon=Icon.BUBBLES,
    name="Spa Bubbles",
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
        features = features_for(device, config_entry.options)
        if features.bubbles in (
            BubblesStyle.THREE_WAY_AIRJET,
            BubblesStyle.THREE_WAY_HYDROJET,
        ):
            entities.append(
                ThreeWaySpaBubblesSelect(coordinator, config_entry, device_id)
            )

    async_add_entities(entities)


class ThreeWaySpaBubblesSelect(BestwayEntity, SelectEntity):
    """Bubbles selection for spa devices that support 3 levels."""

    entity_description: SelectEntityDescription = _BUBBLES_SELECT_DESCRIPTION

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize select."""
        super().__init__(coordinator, config_entry, device_id)
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        if (status := self.status) and status.bubbles is not None:
            return _BUBBLES_OPTIONS.get(status.bubbles)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        bubbles_level = BubblesLevel.OFF
        if option == _BUBBLES_OPTIONS[BubblesLevel.MEDIUM]:
            bubbles_level = BubblesLevel.MEDIUM
        elif option == _BUBBLES_OPTIONS[BubblesLevel.MAX]:
            bubbles_level = BubblesLevel.MAX

        await self.coordinator.api.set_bubbles(self.device_id, bubbles_level)
        await self.coordinator.async_request_refresh()
