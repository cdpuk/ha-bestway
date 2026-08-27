"""Tests for the shared Gizwits (V01) device model."""

from custom_components.bestway.bestway.model import BestwayDeviceType


def test_from_api_product_name():
    """Verify each known Gizwits product_name value maps to its device type."""
    assert (
        BestwayDeviceType.from_api_product_name("Airjet")
        == BestwayDeviceType.AIRJET_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Airjet_V01")
        == BestwayDeviceType.AIRJET_V01_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("UltraFit")
        == BestwayDeviceType.ULTRAFIT_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Hydrojet")
        == BestwayDeviceType.HYDROJET_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("Hydrojet_Pro")
        == BestwayDeviceType.HYDROJET_PRO_SPA
    )
    assert (
        BestwayDeviceType.from_api_product_name("泳池过滤器")
        == BestwayDeviceType.POOL_FILTER
    )


def test_from_api_product_name_unknown():
    """An unrecognised product_name falls back to UNKNOWN."""
    assert (
        BestwayDeviceType.from_api_product_name("SomeNewProduct")
        == BestwayDeviceType.UNKNOWN
    )
