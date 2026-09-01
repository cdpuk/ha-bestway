"""Backend-neutral device and status models.

These types are shared by all three cloud backends (Gizwits, AWS IoT,
SmartSpa) and by the entity layer. Backend-specific wire vocabulary (raw
Gizwits attribute names, the Hydrojet/Airjet_V01 wire constants, the
bubbles read/write maps) lives in `bestway/model.py` instead, since that
vocabulary is Gizwits wire language even when reused by the other two
backends' normalization step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .const import BACKEND_AWS_IOT, BACKEND_GIZWITS, BACKEND_SMARTSPA


class BestwayDeviceType(Enum):
    """Bestway device types."""

    AIRJET_SPA = "Airjet"
    AIRJET_V01_SPA = "Airjet V01"
    ULTRAFIT_SPA = "UltraFit"
    HYDROJET_SPA = "Hydrojet"
    HYDROJET_PRO_SPA = "Hydrojet Pro"
    POOL_FILTER = "Pool Filter"
    UNKNOWN = "Unknown"
    # V02 backend device types (AWS IoT)
    AIRJET_V02 = "Airjet V02"
    ULTRAFIT_AIRJET_V02 = "Ultrafit Airjet V02"
    HYDROJET_V02 = "Hydrojet V02"
    HYDROJET_PRO_V02 = "Hydrojet Pro V02"

    @staticmethod
    def from_api_product_name(product_name: str) -> BestwayDeviceType:
        """Get the enum value based on the 'product_name' field in the API response."""

        if product_name == "Airjet":
            return BestwayDeviceType.AIRJET_SPA
        if product_name == "Airjet_V01":
            return BestwayDeviceType.AIRJET_V01_SPA
        if product_name == "UltraFit":
            return BestwayDeviceType.ULTRAFIT_SPA
        if product_name == "Hydrojet":
            return BestwayDeviceType.HYDROJET_SPA
        if product_name == "Hydrojet_Pro":
            return BestwayDeviceType.HYDROJET_PRO_SPA
        if product_name == "泳池过滤器":
            # Chinese translates to "pool filter"
            return BestwayDeviceType.POOL_FILTER
        return BestwayDeviceType.UNKNOWN

    @staticmethod
    def from_aws_product_series(product_series: str) -> BestwayDeviceType:
        """Get the enum value based on AWS IoT 'product_series' field.

        Args:
            product_series: Product series from AWS IoT API (e.g., "AIRJET", "HYDROJET")

        Returns:
            Corresponding V02 device type enum value
        """
        mapping = {
            "AIRJET": BestwayDeviceType.AIRJET_V02,
            "ULTRAFIT_AIRJET": BestwayDeviceType.ULTRAFIT_AIRJET_V02,
            "HYDROJET": BestwayDeviceType.HYDROJET_V02,
            "HYDROJET_PRO": BestwayDeviceType.HYDROJET_PRO_V02,
        }
        return mapping.get(product_series, BestwayDeviceType.UNKNOWN)


class TemperatureUnit(Enum):
    """Temperature units supported by the spa."""

    CELSIUS = auto()
    FAHRENHEIT = auto()


class HeaterState(Enum):
    """Normalized heater state, independent of any backend's wire encoding."""

    OFF = auto()
    HEATING = auto()
    TARGET_REACHED = auto()


class BubblesLevel(Enum):
    """Bubbles levels available to a range of spa models."""

    OFF = auto()
    MEDIUM = auto()
    MAX = auto()


@dataclass
class BestwayDevice:
    """A device under a user's account."""

    protocol_version: int
    device_id: str
    product_name: str  # For Gizwits: "Airjet", "Hydrojet_Pro", etc.
    alias: str
    mcu_soft_version: str
    mcu_hard_version: str
    wifi_soft_version: str
    wifi_hard_version: str
    is_online: bool
    ws_host: str = "m2m.gizwits.com"  # WebSocket hostname from bindings API
    ws_port: int = 8880  # WebSocket port from bindings API
    backend: str = BACKEND_GIZWITS  # Backend type: gizwits or aws_iot
    product_id: str | None = None  # For AWS IoT: model ID like "T53NN8"
    product_series: str | None = None  # For AWS IoT: series like "AIRJET", "HYDROJET"

    @property
    def device_type(self) -> BestwayDeviceType:
        """Get the derived device type based on backend."""
        if self.backend in (BACKEND_AWS_IOT, BACKEND_SMARTSPA) and self.product_series:
            return BestwayDeviceType.from_aws_product_series(self.product_series)
        return BestwayDeviceType.from_api_product_name(self.product_name)


@dataclass
class RawSnapshot:
    """A backend's internal merge substrate: the last-known wire attrs for a
    device, prior to translation into a `DeviceStatus`.

    This is what each backend's private cache stores. Partial WebSocket
    deltas are merged into this shape (`{**existing.attrs, **attrs}`) before
    being translated, so translation always sees the full accumulated state
    rather than a partial one.
    """

    timestamp: int
    attrs: dict[str, Any]


@dataclass
class DeviceStatus:
    """A normalized snapshot of a device's status, independent of backend.

    All fields default to `None` (or empty) so a sparse status - such as one
    built from a WebSocket delta for a field nobody has read yet - is always
    constructible and safe for entities to read: an absent value simply
    means "unknown", not an error.

    `attrs` retains the raw wire snapshot for diagnostics only; entities
    must read the typed fields above it, never `attrs` directly.
    """

    timestamp: int = 0
    attrs: dict[str, Any] = field(default_factory=dict)
    power: bool | None = None
    filtering: bool | None = None
    heater: HeaterState | None = None
    current_temperature: float | None = None
    target_temperature: float | None = None
    temperature_unit: TemperatureUnit | None = None
    bubbles: BubblesLevel | None = None
    jets: bool | None = None
    locked: bool | None = None
    errors: list[str] = field(default_factory=list)
    filter_timer_hours: int | None = None
    filter_change_required: bool | None = None
    wifi_version: str | int | None = None
    trd_version: str | int | None = None
    ota_status: str | int | None = None


# Compat alias: the type used to be named BestwayDeviceStatus and carried
# only timestamp/attrs. Keeping the name importable avoids a mechanical
# rename across every call site that still says `BestwayDeviceStatus`.
BestwayDeviceStatus = DeviceStatus


@dataclass
class BestwayApiResults:
    """A snapshot of device status reports returned from the API."""

    devices: dict[str, DeviceStatus]
