"""Select platform."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BestwayUpdateCoordinator
from .bestway.model import BestwayDeviceType, HydrojetBubbles
from .const import DOMAIN, Icon
from .entity import BestwayEntity

_HYDROJET_BUBBLES_OPTIONS = {
    HydrojetBubbles.OFF: "OFF",
    HydrojetBubbles.MEDIUM: "MEDIUM",
    HydrojetBubbles.MAX: "MAX",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator: BestwayUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[BestwayEntity] = []

    for device_id, device in coordinator.api.devices.items():
        if device.device_type in [
            BestwayDeviceType.HYDROJET_PRO_SPA,
        ]:
            entities.append(
                HydrojetSpaBubblesSelect(
                    coordinator,
                    config_entry,
                    device_id,
                    SelectEntityDescription(
                        key="bubbles",
                        options=list(_HYDROJET_BUBBLES_OPTIONS.values()),
                        icon=Icon.BUBBLES,
                        name="Spa Bubbles",
                    ),
                )
            )

    async_add_entities(entities)


class HydrojetSpaBubblesSelect(BestwayEntity, SelectEntity):
    """The main thermostat entity for a spa."""

    def __init__(
        self,
        coordinator: BestwayUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize thermostat."""
        super().__init__(coordinator, config_entry, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option."""
        if device := self.coordinator.data.devices.get(self.device_id):
            return _HYDROJET_BUBBLES_OPTIONS.get(device.attrs["wave"])
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        api_value = HydrojetBubbles.OFF
        if option == _HYDROJET_BUBBLES_OPTIONS[HydrojetBubbles.MEDIUM]:
            api_value = HydrojetBubbles.MEDIUM
        elif option == _HYDROJET_BUBBLES_OPTIONS[HydrojetBubbles.MAX]:
            api_value = HydrojetBubbles.MAX

        await self.coordinator.api.hydrojet_spa_set_bubbles(self.device_id, api_value)
