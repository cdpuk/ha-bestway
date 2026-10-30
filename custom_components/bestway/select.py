"""Select platform."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Icon
from .coordinator import BestwayUpdateCoordinator
from .entity import BestwayEntity, OptimisticValue
from .features import BubblesStyle, features_for
from .model import BubblesLevel

# Option values are translation slugs: Home Assistant looks each one up under
# entity.select.bubbles.state in the translation files, so the UI can show them
# in the user's language.
_BUBBLES_OPTIONS = {
    BubblesLevel.OFF: "off",
    BubblesLevel.MEDIUM: "medium",
    BubblesLevel.MAX: "max",
}
_BUBBLES_LEVELS = {option: level for level, option in _BUBBLES_OPTIONS.items()}

# Which bubbles map (Airjet-style vs. Hydrojet-style MEDIUM value) a device
# uses is decided by bubbles_map_for() in translation.py; the entity
# only reads status.bubbles and writes via set_bubbles().
_BUBBLES_SELECT_DESCRIPTION = SelectEntityDescription(
    key="bubbles",
    translation_key="bubbles",
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
        if features.bubbles == BubblesStyle.THREE_WAY:
            entities.append(
                ThreeWaySpaBubblesSelect(coordinator, config_entry, device_id)
            )

    async_add_entities(entities)


class ThreeWaySpaBubblesSelect(BestwayEntity, SelectEntity):
    """Bubbles selection for spa devices that support 3 levels."""

    entity_description: SelectEntityDescription = _BUBBLES_SELECT_DESCRIPTION
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize select."""
        super().__init__(coordinator, config_entry, device_id)
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"
        self._optimistic = OptimisticValue[BubblesLevel]()

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        if self._optimistic.value is not None:
            return _BUBBLES_OPTIONS.get(self._optimistic.value)
        if (status := self.status) and status.bubbles is not None:
            return _BUBBLES_OPTIONS.get(status.bubbles)
        return None

    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state once real data confirms it, or after a
        short timeout - see BestwaySwitch in switch.py for why this is
        needed.
        """
        if self.status is not None:
            self._optimistic.confirm(self.status.bubbles)
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        bubbles_level = _BUBBLES_LEVELS[option]
        self._optimistic.set(bubbles_level)
        self.async_write_ha_state()
        await self.coordinator.api.set_bubbles(self.device_id, bubbles_level)
        await self.coordinator.async_request_refresh()
