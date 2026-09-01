"""Wire attrs -> typed `DeviceStatus` translation.

Every backend ends up speaking one of three Gizwits wire vocabularies by the
time its raw/normalized attrs reach here:

- Raw Airjet (`AIRJET_SPA` only): the only device type Gizwits never
  normalized. Field names like `heat_power`, `wave_power`, `temp_set_unit`.
- The V01 vocabulary: Gizwits V01 devices natively, plus everything AWS IoT
  and SmartSpa emit after their own `normalize_aws_state` step (which
  deliberately targets this same vocabulary). Field names like `heat`,
  `wave`, `Tset`, `Tunit`.
- Pool filter: `power`, `time`, `filter` (meaning "change required" here,
  not "filtering" - the typed model disambiguates what the raw vocabulary
  couldn't).

`status_from_attrs` is the single entry point backends call, after merging
any partial WebSocket delta into their raw cache, to produce the typed
`DeviceStatus` entities read.
"""

from __future__ import annotations

import re
from typing import Any

from ..model import (
    BestwayDeviceType,
    BubblesLevel,
    DeviceStatus,
    HeaterState,
    TemperatureUnit,
)
from .model import AIRJET_V01_BUBBLES_MAP, HYDROJET_BUBBLES_MAP, BubblesMapping

_SYSTEM_ERR_RE = re.compile(r"system_err\d+")
_E_CODE_RE = re.compile(r"E\d{2}")

_HYDROJET_BUBBLES_TYPES = frozenset(
    {
        BestwayDeviceType.HYDROJET_SPA,
        BestwayDeviceType.HYDROJET_PRO_SPA,
        BestwayDeviceType.HYDROJET_V02,
        BestwayDeviceType.HYDROJET_PRO_V02,
    }
)


def _bubbles_map_for(device_type: BestwayDeviceType) -> BubblesMapping:
    """The bubbles read map a normalized-vocabulary device type uses.

    Mirrors the THREE_WAY_AIRJET/THREE_WAY_HYDROJET split in features.py:
    Hydrojet variants read MEDIUM as 40-43, everything else as 40/41/50/51.
    """
    if device_type in _HYDROJET_BUBBLES_TYPES:
        return HYDROJET_BUBBLES_MAP
    return AIRJET_V01_BUBBLES_MAP


def _as_int(value: Any) -> int | None:
    """Best-effort int parse. Returns None rather than raising on anything
    that isn't cleanly convertible (a stale/malformed cache entry should
    surface as "unknown", not crash translation).
    """
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def status_from_attrs(
    device_type: BestwayDeviceType, timestamp: int, attrs: dict[str, Any]
) -> DeviceStatus:
    """Translate a backend's merged wire attrs into a typed `DeviceStatus`."""
    if device_type == BestwayDeviceType.AIRJET_SPA:
        return _from_raw_airjet(timestamp, attrs)
    if device_type == BestwayDeviceType.POOL_FILTER:
        return _from_pool_filter(timestamp, attrs)
    if device_type == BestwayDeviceType.UNKNOWN:
        return DeviceStatus(timestamp=timestamp, attrs=dict(attrs))
    return _from_v01_vocab(device_type, timestamp, attrs)


def _from_raw_airjet(timestamp: int, attrs: dict[str, Any]) -> DeviceStatus:
    heat_power = attrs.get("heat_power")
    heater: HeaterState | None = None
    if heat_power is not None:
        if not heat_power:
            heater = HeaterState.OFF
        elif attrs.get("heat_temp_reach"):
            heater = HeaterState.TARGET_REACHED
        else:
            heater = HeaterState.HEATING

    temp_unit_raw = attrs.get("temp_set_unit")
    temperature_unit: TemperatureUnit | None = None
    if temp_unit_raw is not None:
        temperature_unit = (
            TemperatureUnit.CELSIUS
            if temp_unit_raw == "摄氏"
            else TemperatureUnit.FAHRENHEIT
        )

    wave_power = attrs.get("wave_power")
    bubbles: BubblesLevel | None = None
    if wave_power is not None:
        bubbles = BubblesLevel.MAX if wave_power else BubblesLevel.OFF

    errors = sorted(
        attr
        for attr in attrs
        if (_SYSTEM_ERR_RE.match(attr) or attr == "earth") and attrs[attr]
    )

    return DeviceStatus(
        timestamp=timestamp,
        attrs=dict(attrs),
        power=_as_bool(attrs.get("power")),
        filtering=_as_bool(attrs.get("filter_power")),
        heater=heater,
        current_temperature=_as_int(attrs.get("temp_now")),
        target_temperature=_as_int(attrs.get("temp_set")),
        temperature_unit=temperature_unit,
        bubbles=bubbles,
        locked=_as_bool(attrs.get("locked")),
        errors=errors,
    )


def _from_v01_vocab(
    device_type: BestwayDeviceType, timestamp: int, attrs: dict[str, Any]
) -> DeviceStatus:
    heat = attrs.get("heat")
    heater: HeaterState | None = None
    heat_int = _as_int(heat) if heat is not None else None
    if heat_int is not None:
        if heat_int == 0:
            heater = HeaterState.OFF
        elif heat_int == 4:
            heater = HeaterState.TARGET_REACHED
        else:
            heater = HeaterState.HEATING

    tunit_raw = attrs.get("Tunit")
    temperature_unit: TemperatureUnit | None = None
    if tunit_raw is not None:
        tunit_int = _as_int(tunit_raw)
        temperature_unit = (
            TemperatureUnit.FAHRENHEIT if tunit_int == 0 else TemperatureUnit.CELSIUS
        )

    bubbles: BubblesLevel | None = None
    wave_int = _as_int(attrs.get("wave"))
    if wave_int is not None:
        bubbles = _bubbles_map_for(device_type).from_api_value(wave_int)

    errors = sorted(
        attr
        for attr in attrs
        if attr != "E32" and _E_CODE_RE.match(attr) and attrs[attr]
    )
    if attrs.get("error"):
        errors.append("error")

    return DeviceStatus(
        timestamp=timestamp,
        attrs=dict(attrs),
        power=_as_bool(attrs.get("power")),
        filtering=_as_bool(attrs.get("filter")),
        heater=heater,
        current_temperature=_as_int(attrs.get("Tnow")),
        target_temperature=_as_int(attrs.get("Tset")),
        temperature_unit=temperature_unit,
        bubbles=bubbles,
        jets=_as_bool(attrs.get("jet")),
        locked=_as_bool(attrs.get("locked")),
        errors=errors,
        wifi_version=attrs.get("wifi_version"),
        trd_version=attrs.get("trd_version"),
        ota_status=attrs.get("ota_status"),
    )


def _from_pool_filter(timestamp: int, attrs: dict[str, Any]) -> DeviceStatus:
    errors = ["error"] if attrs.get("error") else []
    timer_hours = attrs.get("time")

    return DeviceStatus(
        timestamp=timestamp,
        attrs=dict(attrs),
        power=_as_bool(attrs.get("power")),
        filter_timer_hours=timer_hours if isinstance(timer_hours, int) else None,
        filter_change_required=_as_bool(attrs.get("filter")),
        errors=errors,
    )
