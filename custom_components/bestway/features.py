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

from .bestway.model import BestwayDevice, BestwayDeviceType
from .const import (
    BACKEND_GIZWITS,
    BUBBLES_MODE_DEFAULT,
    BUBBLES_MODE_ONOFF,
    CONF_BUBBLES_MODE,
)


class ControlFamily(Enum):
    """Which API methods and attribute vocabulary a device speaks."""

    NONE = auto()
    # airjet_spa_set_*, raw attrs "power"/"filter_power"/"wave_power"/"locked"
    RAW_AIRJET = auto()
    # hydrojet_spa_set_*, normalized attrs "power"/"filter"/"jet"/"wave"
    # (shared by Airjet V01, Hydrojet V01/V02, and Airjet V02 - normalization
    # gives them all consistent field names)
    NORMALIZED_SPA = auto()
    POOL_FILTER = auto()


class BubblesStyle(Enum):
    """Which bubbles control (if any) a device gets."""

    NONE = auto()
    LEGACY_SWITCH = auto()  # AIRJET_SPA: plain on/off switch on wave_power
    V02_SWITCH = auto()  # V02 Airjet in on/off mode: switch on wave
    # V02 Hydrojet in on/off mode (e.g. F12D9Q San Francisco HydroJet Pro is
    # on/off only): switch using hydrojet_spa_set_bubbles(MAX/OFF).
    V02_HYDROJET_SWITCH = auto()
    THREE_WAY_AIRJET = auto()  # AIRJET_V01_BUBBLES_MAP + airjet_v01_spa_set_bubbles
    THREE_WAY_HYDROJET = auto()  # HYDROJET_BUBBLES_MAP + hydrojet_spa_set_bubbles


class VersionSensorSet(Enum):
    """Which diagnostic version sensors a device gets."""

    GIZWITS = auto()  # protocol/mcu/wifi versions from the device object
    SHADOW = auto()  # wifi/trd/ota versions from shadow state


@dataclass(frozen=True)
class DeviceFeatures:
    """The set of entities and behaviours supported by a device."""

    control_family: ControlFamily
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
    control_family=ControlFamily.NONE,
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

# This table intentionally reproduces the pre-existing per-platform behaviour
# exactly, asymmetries included. Known asymmetries are marked TODO and are
# corrected in separate follow-up commits so existing installs don't see
# entities appear, disappear, or rename underneath them as a side effect of
# this refactor. Every spa row repeats connectivity_sensor/errors_sensor and
# a name_prefix (usually "Spa") rather than sharing a common base via a dict
# splat, so that mypy's strict checking on this module can verify every field
# by name.
_FEATURES_BY_TYPE: dict[BestwayDeviceType, DeviceFeatures] = {
    BestwayDeviceType.AIRJET_SPA: replace(
        _NO_FEATURES,
        control_family=ControlFamily.RAW_AIRJET,
        climate=True,
        power_switch=True,
        filter_switch=True,
        lock_switch=True,
        bubbles=BubblesStyle.LEGACY_SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.AIRJET_V01_SPA: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        bubbles=BubblesStyle.THREE_WAY_AIRJET,
        connectivity_sensor=True,
        errors_sensor=True,
        # TODO: this should be "Spa" like every other spa type - left as
        # "Bestway" (inherited from _NO_FEATURES) to match pre-refactor
        # behaviour. See sensor.py's old name_prefix list, which omitted
        # AIRJET_V01_SPA.
        name_prefix="Bestway",
    ),
    BestwayDeviceType.ULTRAFIT_SPA: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        bubbles=BubblesStyle.THREE_WAY_AIRJET,
        # TODO: the V02 sibling (ULTRAFIT_AIRJET_V02) can flip to an on/off
        # switch via CONF_BUBBLES_MODE; V01 was never wired up to honour it.
        bubbles_mode_option=False,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_SPA: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY_HYDROJET,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_PRO_SPA: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY_HYDROJET,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.AIRJET_V02: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        # TODO: aws_iot normalizes a "locked" attribute for this device type
        # but no lock switch has ever been created for it. Needs confirmation
        # that airjet_spa_set_locked routes correctly on the AWS backend
        # before enabling.
        lock_switch=False,
        bubbles=BubblesStyle.THREE_WAY_AIRJET,
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.V02_SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.ULTRAFIT_AIRJET_V02: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        # TODO: see AIRJET_V02 above.
        lock_switch=False,
        bubbles=BubblesStyle.THREE_WAY_AIRJET,
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.V02_SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_V02: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY_HYDROJET,
        # V02 Hydrojet hardware varies (F12D9Q San Francisco HydroJet Pro is
        # on/off only), so it honours the same bubbles-mode option as the
        # Airjet V02 family.
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.V02_HYDROJET_SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.HYDROJET_PRO_V02: replace(
        _NO_FEATURES,
        control_family=ControlFamily.NORMALIZED_SPA,
        climate=True,
        power_switch=True,
        filter_switch=True,
        jets_switch=True,
        bubbles=BubblesStyle.THREE_WAY_HYDROJET,
        # See HYDROJET_V02 above.
        bubbles_mode_option=True,
        bubbles_onoff=BubblesStyle.V02_HYDROJET_SWITCH,
        connectivity_sensor=True,
        errors_sensor=True,
        name_prefix="Spa",
    ),
    BestwayDeviceType.POOL_FILTER: replace(
        _NO_FEATURES,
        control_family=ControlFamily.POOL_FILTER,
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
    # set, including UNKNOWN. This mirrors the pre-refactor `else` branch in
    # sensor.py, which gave the shadow-based set to anything that wasn't
    # BACKEND_GIZWITS (i.e. both AWS IoT and SmartSpa).
    version_sensors = (
        VersionSensorSet.GIZWITS
        if device.backend == BACKEND_GIZWITS
        else VersionSensorSet.SHADOW
    )

    bubbles = base.bubbles
    if base.bubbles_mode_option:
        mode = options.get(CONF_BUBBLES_MODE, BUBBLES_MODE_DEFAULT)
        if mode == BUBBLES_MODE_ONOFF:
            bubbles = base.bubbles_onoff

    return replace(base, bubbles=bubbles, version_sensors=version_sensors)
