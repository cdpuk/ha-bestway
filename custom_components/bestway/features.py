"""Per-device-type feature table.

`features_for()` is a pure function of the device's derived `device_type`
(never of the attributes in a status payload - a partial or offline first
poll would otherwise silently drop entities) plus the config entry options
that affect capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Any

from .const import (
    BUBBLES_MODE_DEFAULT,
    BUBBLES_MODE_ONOFF,
    CONF_BUBBLES_MODE,
    Backend,
)
from .model import BestwayDevice, BestwayDeviceType


class DeviceKind(Enum):
    """Broad device category, for the handful of things that differ between
    a spa and a pool filter (name prefix, which power/connectivity/error
    description a device gets). Purely a UI-shape distinction - wire
    vocabulary lives in backend.py / translation.py.
    """

    NONE = auto()
    SPA = auto()
    POOL_FILTER = auto()


class BubblesStyle(Enum):
    """Which bubbles control (if any) a device gets.

    Which read/write map (Airjet-style vs. Hydrojet-style MEDIUM values) a
    THREE_WAY device uses is decided by bubbles_map_for() in
    translation.py, not here.
    """

    NONE = auto()
    SWITCH = auto()  # plain on/off switch
    THREE_WAY = auto()  # OFF/MEDIUM/MAX select


class VersionSensorSet(Enum):
    """Which diagnostic version sensors a device gets."""

    GIZWITS = auto()  # protocol/mcu/wifi versions from the device object
    SHADOW = auto()  # wifi/trd/ota versions from shadow state


@dataclass(frozen=True)
class DeviceFeatures:
    """The set of entities and behaviours supported by a device."""

    device_kind: DeviceKind
    climate: bool
    power_switch: bool
    filter_switch: bool
    jets_switch: bool
    lock_switch: bool
    bubbles: BubblesStyle
    bubbles_mode_option: bool
    # Style substituted for `bubbles` when bubbles_mode_option is set and
    # CONF_BUBBLES_MODE is the on/off choice. Meaningless (left at NONE)
    # when bubbles_mode_option is False.
    bubbles_onoff: BubblesStyle
    pool_filter_timer: bool
    filter_change_sensor: bool
    connectivity_sensor: bool
    errors_sensor: bool
    name_prefix: str
    version_sensors: VersionSensorSet


_NO_FEATURES = DeviceFeatures(
    device_kind=DeviceKind.NONE,
    climate=False,
    power_switch=False,
    filter_switch=False,
    jets_switch=False,
    lock_switch=False,
    bubbles=BubblesStyle.NONE,
    bubbles_mode_option=False,
    bubbles_onoff=BubblesStyle.NONE,
    pool_filter_timer=False,
    filter_change_sensor=False,
    connectivity_sensor=False,
    errors_sensor=False,
    name_prefix="Bestway",
    version_sensors=VersionSensorSet.SHADOW,  # overwritten by features_for()
)

# A table change that adds, removes or renames entities on existing installs
# should be its own commit, with the characterisation tests in
# tests/test_entity_setup.py updated alongside. Every spa row repeats
# connectivity_sensor/errors_sensor and a name_prefix (usually "Spa") rather
# than sharing a common base via a dict splat, so that mypy's strict checking on
# this module can verify every field by name.
_FEATURES_BY_TYPE: dict[BestwayDeviceType, DeviceFeatures] = {
    BestwayDeviceType.AIRJET_SPA: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        lock_switch=True,
        bubbles=BubblesStyle.SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.AIRJET_V01_SPA: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.ULTRAFIT_SPA: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        bubbles_mode_option=False,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_SPA: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_PRO_SPA: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.AIRJET_V02: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        lock_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.ULTRAFIT_AIRJET_V02: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        lock_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_V02: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        # The Bestway app only exposes on/off bubbles, but Hydrojet V02
        # panels (e.g. F12D9Q San Francisco HydroJet Pro) have real
        # OFF/MEDIUM/MAX levels on the touch panel, so the 3-way select is
        # the honest control. Some hardware truly is on/off only, and the
        # product_id doesn't tell them apart, so it honours the same
        # bubbles-mode option as the Airjet V02 family.
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_PRO_V02: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY,
        # See HYDROJET_V02 above.
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.POOL_FILTER: replace(
        _NO_FEATURES,
        device_kind=DeviceKind.POOL_FILTER,
        power_switch=True,
        pool_filter_timer=True,
        filter_change_sensor=True,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Pool Filter",
    ),
    BestwayDeviceType.UNKNOWN: _NO_FEATURES,
}


def features_for(device: BestwayDevice, options: Mapping[str, Any]) -> DeviceFeatures:
    """Derive the supported feature set for a device.

    `options` is the config entry's options mapping.
    """
    base = _FEATURES_BY_TYPE.get(device.device_type, _NO_FEATURES)

    # Version sensors follow the backend, not the model: every device gets a
    # set, including UNKNOWN. Anything that isn't Backend.GIZWITS (AWS IoT,
    # SmartSpa, and any future backend) gets the shadow-based set.
    version_sensors = (
        VersionSensorSet.GIZWITS
        if device.backend == Backend.GIZWITS
        else VersionSensorSet.SHADOW
    )

    bubbles = base.bubbles
    if base.bubbles_mode_option:
        mode = options.get(CONF_BUBBLES_MODE, BUBBLES_MODE_DEFAULT)
        if mode == BUBBLES_MODE_ONOFF:
            bubbles = base.bubbles_onoff

    return replace(base, bubbles=bubbles, version_sensors=version_sensors)


def bubbles_mode_dependent(device: BestwayDevice) -> bool:
    """True if this device type's bubbles control changes shape (switch vs.
    3-way select) depending on the bubbles_mode option.

    Used to identify which entity registry entries are stale after a mode
    change (see _async_remove_orphaned_bubbles_entities in __init__.py).
    """
    return _FEATURES_BY_TYPE.get(device.device_type, _NO_FEATURES).bubbles_mode_option
