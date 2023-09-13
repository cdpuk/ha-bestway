"""Bestway API models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from time import time

# How old the latest update can be before a spa is considered offline
_CONNECTIVITY_TIMEOUT = 1000


class BestwayDeviceType(Enum):
    """Bestway device types."""

    AIRJET_SPA = "Airjet"
    POOL_FILTER = "Pool Filter"
    UNKNOWN = "Unknown"

    @staticmethod
    def from_api_product_name(product_name: str) -> BestwayDeviceType:
        """Get the enum value based on the 'product_name' field in the API response."""

        if product_name == "Airjet":
            return BestwayDeviceType.AIRJET_SPA
        if product_name == "泳池过滤器":
            # Chinese translates to "pool filter"
            return BestwayDeviceType.POOL_FILTER
        return BestwayDeviceType.UNKNOWN


class TemperatureUnit(Enum):
    """Temperature units supported by the spa."""

    CELSIUS = auto()
    FAHRENHEIT = auto()


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

    @property
    def online(self) -> bool:
        """Determine whether the device is online based on the age of the latest update."""
        return self.timestamp > (time() - _CONNECTIVITY_TIMEOUT)


@dataclass
class BestwaySpaDeviceStatus(BestwayDeviceStatus):
    """A snapshot of the status of a spa (i.e. Lay-Z-Spa) device."""

    spa_power: bool
    temp_now: float
    temp_set: float
    temp_set_unit: TemperatureUnit
    heat_power: bool
    heat_temp_reach: bool
    filter_power: bool
    wave_power: bool
    locked: bool
    errors: list[int]
    earth_fault: bool


@dataclass
class BestwayPoolFilterDeviceStatus(BestwayDeviceStatus):
    """A snapshot of the status of a filter device."""

    timestamp: int
    filter_change_required: bool
    power: bool
    time: int
    running: bool
    error: bool


@dataclass
class BestwayUserToken:
    """User authentication token, obtained (and ideally stored) following a successful login."""

    user_id: str
    user_token: str
    expiry: int
