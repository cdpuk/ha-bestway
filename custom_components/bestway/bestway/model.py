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
    HYDROJET_PRO_SPA = "Hydrojet Pro"
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
        if product_name == "Hydrojet_Pro":
            return BestwayDeviceType.HYDROJET_PRO_SPA
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


class BubblesValues:
    """Values that represent a given level of bubbles.

    The write_value is the integer used to set the level via the API.

    The read_values list contains a set of integers that may be read from the API to signal the
    desired state. This came about because different users of Airjet_V01 devices reported that
    their app/device would sometimes represent MEDIUM bubbles as 50, but sometimes as 51.
    """

    write_value: int
    read_values: list[int]

    def __init__(self, write_value: int, read_values: list[int] | None = None) -> None:
        """Define the values used for a specific bubbles level."""
        self.write_value = write_value
        if read_values:
            self.read_values = read_values
        else:
            self.read_values = [write_value]


class BubblesMapping:
    """Maps off, medium and max bubbles levels to integer API values."""

    def __init__(
        self, off_val: BubblesValues, medium_val: BubblesValues, max_val: BubblesValues
    ) -> None:
        """Construct a bubbles mapping using the given integer values."""
        self.off_val = off_val
        self.medium_val = medium_val
        self.max_val = max_val

    def to_api_value(self, level: BubblesLevel) -> int:
        """Get the API value to be used when setting the given bubbles level."""

        if level == BubblesLevel.MAX:
            return self.max_val.write_value
        elif level == BubblesLevel.MEDIUM:
            return self.medium_val.write_value
        else:
            return self.off_val.write_value

    def from_api_value(self, value: int) -> BubblesLevel:
        """Get the enum value based on the 'wave' field in the API response."""

        if value in self.max_val.read_values:
            return BubblesLevel.MAX
        if value in self.medium_val.read_values:
            return BubblesLevel.MEDIUM
        if value in self.off_val.read_values:
            return BubblesLevel.OFF

        _LOGGER.warning("Unexpected API value %d - assuming OFF", value)
        return BubblesLevel.OFF


BV = BubblesValues
AIRJET_V01_BUBBLES_MAP = BubblesMapping(BV(0), BV(50, [50, 51]), BV(100))
HYDROJET_BUBBLES_MAP = BubblesMapping(BV(0), BV(40), BV(100))


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
