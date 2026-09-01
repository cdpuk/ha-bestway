"""Gizwits wire-vocabulary models.

Backend-neutral types (`BestwayDevice`, `BestwayDeviceType`, `BubblesLevel`,
`TemperatureUnit`, `DeviceStatus`/`BestwayDeviceStatus`, `BestwayApiResults`)
live in the top-level `..model` module and are re-exported here so existing
import paths keep working. What's left in this module is genuinely Gizwits
wire language: the raw integer/enum values POSTed to and read from the
Gizwits control API, which the other two backends translate away from as
part of normalizing into the shared vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from logging import getLogger

from ..model import (
    BestwayApiResults,
    BestwayDevice,
    BestwayDeviceStatus,
    BestwayDeviceType,
    BubblesLevel,
    DeviceStatus,
    HeaterState,
    RawSnapshot,
    TemperatureUnit,
)

# Re-exported for existing import paths - see module docstring.
__all__ = [
    "AIRJET_V01_BUBBLES_MAP",
    "HYDROJET_BUBBLES_MAP",
    "BestwayApiResults",
    "BestwayDevice",
    "BestwayDeviceStatus",
    "BestwayDeviceType",
    "BestwayUserToken",
    "BubblesLevel",
    "BubblesMapping",
    "BubblesValues",
    "DeviceStatus",
    "HeaterState",
    "HydrojetFilter",
    "HydrojetHeat",
    "RawSnapshot",
    "TemperatureUnit",
]

_LOGGER = getLogger(__name__)


class HydrojetFilter(IntEnum):
    """Airjet_V01/Hydrojet filter values."""

    OFF = 0
    ON = 2


class HydrojetHeat(IntEnum):
    """Airjet_V01/Hydrojet heater values."""

    OFF = 0
    ON = 3


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
AIRJET_V01_BUBBLES_MAP = BubblesMapping(BV(0), BV(50, [40, 41, 50, 51]), BV(100))
# Hydrojet V02 (e.g. product T8HDVS) reports MEDIUM as 42, not 40 — the same
# kind of per-firmware drift that PR #101 handled for Airjet (40/41/50/51).
# Accept a 40-43 band for MEDIUM so the running state is recognised instead of
# logging "Unexpected API value 42 - assuming OFF" and showing the tile as OFF.
# Write value stays 40 (the device accepts 40 as the "go to medium" command).
HYDROJET_BUBBLES_MAP = BubblesMapping(BV(0), BV(40, [40, 41, 42, 43]), BV(100))


@dataclass
class BestwayUserToken:
    """User authentication token, obtained (and ideally stored) following a successful login."""

    user_id: str
    user_token: str
    expiry: int
