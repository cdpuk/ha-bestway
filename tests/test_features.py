"""Tests for the device feature table (features.py)."""

import pytest

from custom_components.bestway.bestway.model import BestwayDevice, BestwayDeviceType
from custom_components.bestway.const import (
    BACKEND_AWS_IOT,
    BACKEND_GIZWITS,
    BACKEND_SMARTSPA,
    BUBBLES_MODE_3WAY,
    BUBBLES_MODE_ONOFF,
    CONF_BUBBLES_MODE,
)
from custom_components.bestway.features import (
    BubblesStyle,
    VersionSensorSet,
    features_for,
)


def _device(
    device_type: BestwayDeviceType, backend: str = BACKEND_GIZWITS
) -> BestwayDevice:
    """Build a BestwayDevice that resolves to the given device_type."""
    if backend == BACKEND_GIZWITS:
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

    Airjet V02 flips to a plain on/off switch using airjet_spa_set_bubbles;
    Hydrojet V02 (e.g. F12D9Q San Francisco HydroJet Pro, which is on/off
    only) flips to a switch using hydrojet_spa_set_bubbles instead - they
    are different control families and must not share a switch description.
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
    ):
        device = _device(device_type, backend=BACKEND_AWS_IOT)
        assert features_for(device, onoff).bubbles == BubblesStyle.V02_SWITCH
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY_AIRJET

    for device_type in (
        BestwayDeviceType.HYDROJET_V02,
        BestwayDeviceType.HYDROJET_PRO_V02,
    ):
        device = _device(device_type, backend=BACKEND_AWS_IOT)
        assert features_for(device, onoff).bubbles == BubblesStyle.V02_HYDROJET_SWITCH
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY_HYDROJET

    for device_type in (
        BestwayDeviceType.AIRJET_V01_SPA,
        BestwayDeviceType.ULTRAFIT_SPA,
    ):
        device = _device(device_type)
        assert features_for(device, onoff).bubbles == BubblesStyle.THREE_WAY_AIRJET
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY_AIRJET

    for device_type in (
        BestwayDeviceType.HYDROJET_SPA,
        BestwayDeviceType.HYDROJET_PRO_SPA,
    ):
        device = _device(device_type)
        assert features_for(device, onoff).bubbles == BubblesStyle.THREE_WAY_HYDROJET
        assert features_for(device, threeway).bubbles == BubblesStyle.THREE_WAY_HYDROJET


def test_bubbles_mode_defaults_to_three_way() -> None:
    """With no option set, V02 Airjet defaults to the pre-existing 3-way UI."""
    device = _device(BestwayDeviceType.AIRJET_V02, backend=BACKEND_AWS_IOT)
    assert features_for(device, {}).bubbles == BubblesStyle.THREE_WAY_AIRJET


@pytest.mark.parametrize(
    "backend", [BACKEND_AWS_IOT, BACKEND_SMARTSPA, "some_future_backend"]
)
def test_version_sensors_follow_backend_not_gizwits(backend: str) -> None:
    """Anything other than Gizwits gets the shadow-based version sensor set.

    Mirrors the pre-refactor `else` branch in sensor.py, which used an
    `else` (not an explicit AWS/SmartSpa check) so any future backend falls
    through to the shadow set by default.
    """
    device = _device(BestwayDeviceType.AIRJET_V02, backend=backend)
    assert features_for(device, {}).version_sensors == VersionSensorSet.SHADOW


def test_version_sensors_gizwits() -> None:
    device = _device(BestwayDeviceType.AIRJET_SPA, backend=BACKEND_GIZWITS)
    assert features_for(device, {}).version_sensors == VersionSensorSet.GIZWITS


def test_unknown_device_gets_diagnostics_only() -> None:
    """UNKNOWN devices get a name prefix and version sensors, nothing else."""
    device = _device(BestwayDeviceType.UNKNOWN)
    features = features_for(device, {})
    assert features.name_prefix == "Bestway"
    assert not features.climate
    assert not features.power_switch
    assert not features.connectivity_sensor
