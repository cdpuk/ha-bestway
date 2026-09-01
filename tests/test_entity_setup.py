"""Characterisation tests for per-platform entity setup.

These call each platform's `async_setup_entry` for every BestwayDeviceType
(and both bubbles_mode option values) and assert the exact set of
unique_ids produced. They exist to pin down current behaviour - including
known asymmetries between device types - before/during a refactor from
hardcoded per-platform device-type lists to a shared feature table
(features.py). The set of unique_ids must not change as a result of that
refactor; only the *mechanism* producing them should change.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.bestway import binary_sensor, climate, number, select, sensor
from custom_components.bestway import switch as switch_platform
from custom_components.bestway.const import (
    BUBBLES_MODE_3WAY,
    BUBBLES_MODE_ONOFF,
    CONF_BUBBLES_MODE,
    DOMAIN,
    Backend,
)
from custom_components.bestway.model import (
    BestwayApiResults,
    BestwayDevice,
    BestwayDeviceStatus,
    BestwayDeviceType,
)

_ENTRY_ID = "test_entry"
_DEVICE_ID = "test_device"

# Gizwits product_name for each V01 device type (see BestwayDeviceType.from_api_product_name)
_GIZWITS_PRODUCT_NAME = {
    BestwayDeviceType.AIRJET_SPA: "Airjet",
    BestwayDeviceType.AIRJET_V01_SPA: "Airjet_V01",
    BestwayDeviceType.ULTRAFIT_SPA: "UltraFit",
    BestwayDeviceType.HYDROJET_SPA: "Hydrojet",
    BestwayDeviceType.HYDROJET_PRO_SPA: "Hydrojet_Pro",
    BestwayDeviceType.POOL_FILTER: "泳池过滤器",
}

# AWS product_series for each V02 device type (see BestwayDeviceType.from_aws_product_series)
_AWS_PRODUCT_SERIES = {
    BestwayDeviceType.AIRJET_V02: "AIRJET",
    BestwayDeviceType.ULTRAFIT_AIRJET_V02: "ULTRAFIT_AIRJET",
    BestwayDeviceType.HYDROJET_V02: "HYDROJET",
    BestwayDeviceType.HYDROJET_PRO_V02: "HYDROJET_PRO",
}

ALL_DEVICE_TYPES = list(BestwayDeviceType)

_PLATFORMS = [switch_platform, climate, select, sensor, binary_sensor, number]


def _make_device(device_type: BestwayDeviceType) -> BestwayDevice:
    """Build a BestwayDevice whose derived device_type is device_type."""
    if device_type in _AWS_PRODUCT_SERIES:
        return BestwayDevice(
            protocol_version=2,
            device_id=_DEVICE_ID,
            product_name=_AWS_PRODUCT_SERIES[device_type],
            alias="Test Device",
            mcu_soft_version="1.0",
            mcu_hard_version="1.0",
            wifi_soft_version="1.0",
            wifi_hard_version="1.0",
            is_online=True,
            backend=Backend.AWS_IOT,
            product_id="TESTMODEL",
            product_series=_AWS_PRODUCT_SERIES[device_type],
        )

    product_name = _GIZWITS_PRODUCT_NAME.get(device_type, "Something Unrecognised")
    return BestwayDevice(
        protocol_version=1,
        device_id=_DEVICE_ID,
        product_name=product_name,
        alias="Test Device",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
        backend=Backend.GIZWITS,
    )


def _make_status() -> BestwayDeviceStatus:
    """A status payload with every attribute any platform might read.

    Entity setup itself never reads attrs (only entity properties do, and
    those aren't exercised here), so the exact values don't matter - only
    that lookups used at *construction* time (there are none) wouldn't
    raise.
    """
    return BestwayDeviceStatus(timestamp=1000, attrs={})


async def _setup_all_platforms(
    device_type: BestwayDeviceType, bubbles_mode: str
) -> set[str]:
    """Run every platform's async_setup_entry for one device and return
    the union of unique_ids created.
    """
    device = _make_device(device_type)
    status = _make_status()

    coordinator = MagicMock()
    coordinator.api = MagicMock()
    coordinator.api.devices = {_DEVICE_ID: device}
    coordinator.data = BestwayApiResults(devices={_DEVICE_ID: status})
    coordinator.last_update_success = True

    hass = MagicMock()
    hass.data = {DOMAIN: {_ENTRY_ID: coordinator}}

    config_entry = MagicMock()
    config_entry.entry_id = _ENTRY_ID
    config_entry.options = {CONF_BUBBLES_MODE: bubbles_mode}

    unique_ids: set[str] = set()

    def _add_entities(entities: list) -> None:
        for entity in entities:
            assert entity.unique_id not in unique_ids, (
                f"duplicate unique_id {entity.unique_id!r}"
            )
            unique_ids.add(entity.unique_id)

    for platform in _PLATFORMS:
        await platform.async_setup_entry(hass, config_entry, _add_entities)

    return unique_ids


# Expected unique_id sets, captured directly from the pre-refactor
# implementation by running _setup_all_platforms() against it for every
# (device_type, bubbles_mode) combination. This is the golden baseline the
# refactor (hardcoded per-platform lists -> features.py) must reproduce
# exactly, asymmetries included.
_EXPECTED: dict[tuple[BestwayDeviceType, str], set[str]] = {
    (BestwayDeviceType.AIRJET_SPA, BUBBLES_MODE_3WAY): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.AIRJET_SPA, BUBBLES_MODE_ONOFF): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.AIRJET_V01_SPA, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.AIRJET_V01_SPA, BUBBLES_MODE_ONOFF): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.ULTRAFIT_SPA, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.ULTRAFIT_SPA, BUBBLES_MODE_ONOFF): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.HYDROJET_SPA, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.HYDROJET_SPA, BUBBLES_MODE_ONOFF): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.HYDROJET_PRO_SPA, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.HYDROJET_PRO_SPA, BUBBLES_MODE_ONOFF): {
        "test_device_bubbles",
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.POOL_FILTER, BUBBLES_MODE_3WAY): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_pool_filter_change_required",
        "test_device_pool_filter_connected",
        "test_device_pool_filter_has_error",
        "test_device_pool_filter_power",
        "test_device_pool_filter_time",
        "test_device_protocol_version",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.POOL_FILTER, BUBBLES_MODE_ONOFF): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_pool_filter_change_required",
        "test_device_pool_filter_connected",
        "test_device_pool_filter_has_error",
        "test_device_pool_filter_power",
        "test_device_pool_filter_time",
        "test_device_protocol_version",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.UNKNOWN, BUBBLES_MODE_3WAY): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.UNKNOWN, BUBBLES_MODE_ONOFF): {
        "test_device_mcu_hard_version",
        "test_device_mcu_soft_version",
        "test_device_protocol_version",
        "test_device_wifi_hard_version",
        "test_device_wifi_soft_version",
    },
    (BestwayDeviceType.AIRJET_V02, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.AIRJET_V02, BUBBLES_MODE_ONOFF): {
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.ULTRAFIT_AIRJET_V02, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.ULTRAFIT_AIRJET_V02, BUBBLES_MODE_ONOFF): {
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_locked",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.HYDROJET_V02, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.HYDROJET_V02, BUBBLES_MODE_ONOFF): {
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.HYDROJET_PRO_V02, BUBBLES_MODE_3WAY): {
        "test_device_bubbles",
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
    (BestwayDeviceType.HYDROJET_PRO_V02, BUBBLES_MODE_ONOFF): {
        "test_device_ota_status",
        "test_device_spa_connected",
        "test_device_spa_filter_power",
        "test_device_spa_has_error",
        "test_device_spa_jets",
        "test_device_spa_power",
        "test_device_spa_wave_power",
        "test_device_thermostat",
        "test_device_trd_version",
        "test_device_wifi_version",
    },
}


@pytest.mark.parametrize("device_type", ALL_DEVICE_TYPES)
@pytest.mark.parametrize("bubbles_mode", [BUBBLES_MODE_3WAY, BUBBLES_MODE_ONOFF])
async def test_entity_setup_matches_expected(
    device_type: BestwayDeviceType, bubbles_mode: str
) -> None:
    """The exact set of unique_ids created for each (type, mode) pair."""
    actual = await _setup_all_platforms(device_type, bubbles_mode)
    expected = _EXPECTED[(device_type, bubbles_mode)]
    assert actual == expected
