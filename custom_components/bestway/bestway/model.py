"""Bestway API models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from logging import getLogger

from typing import Any

_LOGGER = getLogger(__name__)


class BestwayDeviceType(Enum):
    """Bestway device types."""

    AIRJET_SPA = "Airjet"
    AIRJET_V01_SPA = "Airjet V01"
    HYDROJET_SPA = "Hydrojet"
    POOL_FILTER = "Pool Filter"
    UNKNOWN = "Unknown"

    @staticmethod
    def from_api_product_name(product_name: str) -> BestwayDeviceType:
        """Get the enum value based on the 'product_name' field in the API response."""

        if product_name == "Airjet":
            return BestwayDeviceType.AIRJET_SPA
        if product_name == "Airjet_V01":
            return BestwayDeviceType.AIRJET_V01_SPA
        if product_name == "Hydrojet":
            return BestwayDeviceType.HYDROJET_SPA
        if product_name == "泳池过滤器":
            # Chinese translates to "pool filter"
            return BestwayDeviceType.POOL_FILTER
        return BestwayDeviceType.UNKNOWN


class TemperatureUnit(Enum):
    """Temperature units supported by the spa."""

    CELSIUS = auto()
    FAHRENHEIT = auto()


class HydrojetFilter(IntEnum):
    """Airjet_V01/Hydrojet filter values."""

    OFF = 0
    ON = 2


class HydrojetHeat(IntEnum):
    """Airjet_V01/Hydrojet heater values."""

    OFF = 0
    ON = 3


class BubblesLevel(Enum):
    """Bubbles levels available to a range of spa models."""

    OFF = auto()
    MEDIUM = auto()
    MAX = auto()


class BubblesMapping:
    """Maps off, medium and max bubbles levels to integer API values."""

    def __init__(self, off_val: int, medium_val: int, max_val: int) -> None:
        """Construct a bubbles mapping using the given integer values."""
        self.off_val = off_val
        self.medium_val = medium_val
        self.max_val = max_val

    def to_api_value(self, level: BubblesLevel) -> int:
        """Get the API value to be used for the given bubbles level."""

        if level == BubblesLevel.MAX:
            return self.max_val
        elif level == BubblesLevel.MEDIUM:
            return self.medium_val
        else:
            return self.off_val

    def from_api_value(self, value: int) -> BubblesLevel:
        """Get the enum value based on the 'wave' field in the API response."""

        if value == self.max_val:
            return BubblesLevel.MAX
        if value == self.medium_val:
            return BubblesLevel.MEDIUM
        if value == self.off_val:
            return BubblesLevel.OFF

        _LOGGER.warning("Unexpected API value %d - assuming OFF", value)
        return BubblesLevel.OFF


AIRJET_V01_BUBBLES_MAP = BubblesMapping(0, 50, 100)
HYDROJET_BUBBLES_MAP = BubblesMapping(0, 40, 100)


@dataclass
class BestwayDevice:
    """A device under a user's account."""

    protocol_version: int
    device_id: str
    product_name: str
    alias: str
    mcu_soft_version: str
    mcu_hard_version: str
    wifi_soft_version: str
    wifi_hard_version: str
    is_online: bool

    @property
    def device_type(self) -> BestwayDeviceType:
        """Get the derived device type."""
        return BestwayDeviceType.from_api_product_name(self.product_name)


@dataclass
class BestwayDeviceStatus:
    """A snapshot of the status of a spa (i.e. Lay-Z-Spa) device."""

    timestamp: int
    attrs: dict[str, Any]


@dataclass
class BestwayUserToken:
    """User authentication token, obtained (and ideally stored) following a successful login."""

    user_id: str
    user_token: str
    expiry: int
