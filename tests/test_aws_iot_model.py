"""Tests for AWS IoT model extensions."""

from custom_components.bestway.bestway.model import (
    HYDROJET_BUBBLES_MAP,
    BestwayDevice,
    BestwayDeviceType,
    BubblesLevel,
)


def test_hydrojet_bubbles_map_reads_medium_band():
    """Hydrojet V02 firmware reports MEDIUM as 42, not 40 (BUG-SPA-6).

    Accept the 40-43 band as MEDIUM so the running state is recognised
    instead of falling back to OFF, while the command value stays 40.
    """
    assert HYDROJET_BUBBLES_MAP.from_api_value(0) == BubblesLevel.OFF
    for medium in (40, 41, 42, 43):
        assert HYDROJET_BUBBLES_MAP.from_api_value(medium) == BubblesLevel.MEDIUM
    assert HYDROJET_BUBBLES_MAP.from_api_value(100) == BubblesLevel.MAX
    # The command sent to the device for MEDIUM is unchanged.
    assert HYDROJET_BUBBLES_MAP.to_api_value(BubblesLevel.MEDIUM) == 40


def test_from_aws_product_series_mappings():
    """Test V02 product series to device type mappings."""
    assert (
        BestwayDeviceType.from_aws_product_series("AIRJET")
        == BestwayDeviceType.AIRJET_V02
    )
    assert (
        BestwayDeviceType.from_aws_product_series("ULTRAFIT_AIRJET")
        == BestwayDeviceType.ULTRAFIT_AIRJET_V02
    )
    assert (
        BestwayDeviceType.from_aws_product_series("HYDROJET")
        == BestwayDeviceType.HYDROJET_V02
    )
    assert (
        BestwayDeviceType.from_aws_product_series("HYDROJET_PRO")
        == BestwayDeviceType.HYDROJET_PRO_V02
    )


def test_from_aws_product_series_unknown():
    """Test unknown and empty product series return UNKNOWN."""
    assert (
        BestwayDeviceType.from_aws_product_series("UNKNOWN_SERIES")
        == BestwayDeviceType.UNKNOWN
    )
    assert BestwayDeviceType.from_aws_product_series("") == BestwayDeviceType.UNKNOWN


def test_bestway_device_backend_default_gizwits():
    """Test BestwayDevice backend field defaults to 'gizwits'."""
    device = BestwayDevice(
        protocol_version=1,
        device_id="test123",
        product_name="Airjet",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
    )
    assert device.backend == "gizwits"


def test_bestway_device_backend_aws_iot():
    """Test BestwayDevice with AWS IoT backend."""
    device = BestwayDevice(
        protocol_version=1,
        device_id="test123",
        product_name="AIRJET",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
        backend="aws_iot",
    )
    assert device.backend == "aws_iot"


def test_from_api_product_name_still_works():
    """Verify existing Gizwits product name mapping unchanged."""
    assert (
        BestwayDeviceType.from_api_product_name("Airjet")
        == BestwayDeviceType.AIRJET_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Airjet_V01")
        == BestwayDeviceType.AIRJET_V01_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Hydrojet")
        == BestwayDeviceType.HYDROJET_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Hydrojet_Pro")
        == BestwayDeviceType.HYDROJET_PRO_SPA
    )
