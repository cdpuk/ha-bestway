"""Tests for the device feature table (features.py)."""

from typing import cast

import pytest

from custom_components.bestway.const import (
    BUBBLES_MODE_3WAY,
    BUBBLES_MODE_ONOFF,
    CONF_BUBBLES_MODE,
    Backend,
)
from custom_components.bestway.features import (
    BubblesStyle,
    DeviceKind,
    VersionSensorSet,
    bubbles_mode_dependent,
    features_for,
)
from custom_components.bestway.model import BestwayDevice, BestwayDeviceType


def _device(
    device_type: BestwayDeviceType, backend: Backend = Backend.GIZWITS
) -> BestwayDevice:
    """Build a BestwayDevice that resolves to the given device_type."""
    if backend == Backend.GIZWITS:
        product_name = {
            BestwayDeviceType.AIRJET_SPA: "Airjet",
            BestwayDeviceType.AIRJET_V01_SPA: "Airjet_V01",
            BestwayDeviceType.ULTRAFIT_SPA: "UltraFit",
            BestwayDeviceType.HYDROJET_SPA: "Hydrojet",
            BestwayDeviceType.HYDROJET_PRO_SPA: "Hydrojet_Pro",
            BestwayDeviceType.POOL_FILTER: "泳池过滤器",
            BestwayDeviceType.UNKNOWN: "Something Else",
        }[device_type]
        return BestwayDevice(
            protocol_version=1,
            device_id="dev",
            product_name=product_name,
            alias="Test",
            mcu_soft_version="1",
            mcu_hard_version="1",
            wifi_soft_version="1",
            wifi_hard_version="1",
            is_online=True,
            backend=backend,
        )

    product_series = {
        BestwayDeviceType.AIRJET_V02: "AIRJET",
        BestwayDeviceType.ULTRAFIT_AIRJET_V02: "ULTRAFIT_AIRJET",
        BestwayDeviceType.HYDROJET_V02: "HYDROJET",
        BestwayDeviceType.HYDROJET_PRO_V02: "HYDROJET_PRO",
        BestwayDeviceType.UNKNOWN: "SOMETHING_ELSE",
    }[device_type]
    return BestwayDevice(
        protocol_version=2,
        device_id="dev",
        product_name=product_series,
        alias="Test",
        mcu_soft_version="1",
        mcu_hard_version="1",
        wifi_soft_version="1",
        wifi_hard_version="1",
        is_online=True,
        backend=backend,
        product_series=product_series,
    )


@pytest.mark.parametrize("device_type", list(BestwayDeviceType))
def test_every_device_type_has_a_row(device_type: BestwayDeviceType) -> None:
    """Every BestwayDeviceType must resolve to a DeviceFeatures row.

    Parametrizing over the live enum means a newly added device type without
    a corresponding row fails this test rather than silently falling back to
    _NO_FEATURES.
    """
    from custom_components.bestway.features import _FEATURES_BY_TYPE

    assert device_type in _FEATURES_BY_TYPE


def test_bubbles_mode_option_flips_only_v02_types() -> None:
    """CONF_BUBBLES_MODE should only affect the four V02 device types.

    All four flip to a plain on/off switch (BubblesStyle.SWITCH); which
    wire vocabulary/map the switch actually uses (Airjet-style vs.
    Hydrojet-style) is decided by bubbles_map_for() in
    bestway/translation.py, not something features.py distinguishes.
    V01 types (Airjet, its ULTRAFIT_SPA sibling, and both V01 Hydrojets)
    always stay three-way; V01 Airjet was never wired up to honour the
    option (see the TODO in features.py), and V01 Hydrojet has no on/off
    hardware variant to switch to.
    """
    onoff = {CONF_BUBBLES_MODE: BUBBLES_MODE_ONOFF}
    threeway = {CONF_BUBBLES_MODE: BUBBLES_MODE_3WAY}

    for device_type in (
        BestwayDeviceType.AIRJET_V02,
        BestwayDeviceType.ULTRAFIT_AIRJET_V02,
        BestwayDeviceType.HYDROJET_V02,
        BestwayDeviceType.HYDROJET_PRO_V02,
    ):
        device = _device(device_type, backend=Backend.AWS_IOT)
        assert features_for(device, onoff).bubbles == BubblesStyle.SWITCH
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY

    for device_type in (
        BestwayDeviceType.AIRJET_V01_SPA,
        BestwayDeviceType.ULTRAFIT_SPA,
        BestwayDeviceType.HYDROJET_SPA,
        BestwayDeviceType.HYDROJET_PRO_SPA,
    ):
        device = _device(device_type)
        assert features_for(device, onoff).bubbles == BubblesStyle.THREE_WAY
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY


def test_bubbles_mode_defaults_to_three_way() -> None:
    """With no option set, V02 Airjet defaults to the pre-existing 3-way UI."""
    device = _device(BestwayDeviceType.AIRJET_V02, backend=Backend.AWS_IOT)
    assert features_for(device, {}).bubbles == BubblesStyle.THREE_WAY


@pytest.mark.parametrize(
    "backend",
    [
        Backend.AWS_IOT,
        Backend.SMARTSPA,
        # Not a real Backend member - a future backend value this build
        # doesn't know about yet should still fall through to shadow sensors.
        cast("Backend", "some_future_backend"),
    ],
)
def test_version_sensors_follow_backend_not_gizwits(backend: Backend) -> None:
    """Anything other than Gizwits gets the shadow-based version sensor set.

    Mirrors the `else` branch in sensor.py, which uses `else` (not an
    explicit AWS/SmartSpa check) so any future backend falls through to the
    shadow set by default.
    """
    device = _device(BestwayDeviceType.AIRJET_V02, backend=backend)
    assert features_for(device, {}).version_sensors == VersionSensorSet.SHADOW


def test_version_sensors_gizwits() -> None:
    device = _device(BestwayDeviceType.AIRJET_SPA, backend=Backend.GIZWITS)
    assert features_for(device, {}).version_sensors == VersionSensorSet.GIZWITS


def test_unknown_device_gets_diagnostics_only() -> None:
    """UNKNOWN devices get a name prefix and version sensors, nothing else."""
    device = _device(BestwayDeviceType.UNKNOWN)
    features = features_for(device, {})
    assert features.name_prefix == "Bestway"
    assert not features.climate
    assert not features.power_switch
    assert not features.connectivity_sensor


def test_device_kind_distinguishes_spa_from_pool_filter() -> None:
    spa = _device(BestwayDeviceType.AIRJET_SPA)
    pool = _device(BestwayDeviceType.POOL_FILTER)
    unknown = _device(BestwayDeviceType.UNKNOWN)
    assert features_for(spa, {}).device_kind == DeviceKind.SPA
    assert features_for(pool, {}).device_kind == DeviceKind.POOL_FILTER
    assert features_for(unknown, {}).device_kind == DeviceKind.NONE


def test_bubbles_mode_dependent_only_true_for_v02_types() -> None:
    """Mirrors the bubbles_mode_option column: only the four V02 types."""
    for device_type in (
        BestwayDeviceType.AIRJET_V02,
        BestwayDeviceType.ULTRAFIT_AIRJET_V02,
        BestwayDeviceType.HYDROJET_V02,
        BestwayDeviceType.HYDROJET_PRO_V02,
    ):
        assert bubbles_mode_dependent(_device(device_type, backend=Backend.AWS_IOT))

    for device_type in (
        BestwayDeviceType.AIRJET_SPA,
        BestwayDeviceType.AIRJET_V01_SPA,
        BestwayDeviceType.HYDROJET_SPA,
        BestwayDeviceType.POOL_FILTER,
        BestwayDeviceType.UNKNOWN,
    ):
        assert not bubbles_mode_dependent(_device(device_type))
