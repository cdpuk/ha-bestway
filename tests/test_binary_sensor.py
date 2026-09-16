"""Binary sensor entity categories.

`Entity.entity_category` falls back to `entity_description.entity_category`
unless the entity itself sets `_attr_entity_category`. The connectivity
sensors set it in their descriptions and belong in the device page's
diagnostics section, but the error and filter-change sensors are user-facing
PROBLEM sensors: forcing those into diagnostics tucks them away where nobody
notices them going off, so nothing in those entity classes may set the
attribute.
"""

from unittest.mock import MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.bestway.binary_sensor import (
    _POOL_FILTER_CONNECTIVITY_SENSOR_DESCRIPTION,
    _POOL_FILTER_ERROR_SENSOR_DESCRIPTION,
    _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
    _SPA_ERRORS_SENSOR_DESCRIPTION,
    DeviceConnectivitySensor,
    DeviceErrorsSensor,
    PoolFilterChangeRequiredSensor,
)
from custom_components.bestway.model import (
    BestwayApiResults,
    BestwayDevice,
    DeviceStatus,
)


def _make_devices() -> BestwayApiResults:
    status = DeviceStatus(timestamp=1000, attrs={"is_online": True})
    return BestwayApiResults(devices={"test_device": status})


def _make_coordinator() -> MagicMock:
    device = BestwayDevice(
        protocol_version=2,
        device_id="test_device",
        product_name="AIRJET",
        alias="Test Spa",
        mcu_soft_version="1.0",
        mcu_hard_version="1.0",
        wifi_soft_version="1.0",
        wifi_hard_version="1.0",
        is_online=True,
    )
    coordinator = MagicMock()
    coordinator.api = MagicMock()
    coordinator.api.devices = {"test_device": device}
    coordinator.data = _make_devices()
    coordinator.last_update_success = True
    return coordinator


def test_connectivity_sensors_are_diagnostic() -> None:
    """The connectivity sensors come from their descriptions, unchanged."""
    coordinator = _make_coordinator()

    for description in (
        _SPA_CONNECTIVITY_SENSOR_DESCRIPTION,
        _POOL_FILTER_CONNECTIVITY_SENSOR_DESCRIPTION,
    ):
        sensor = DeviceConnectivitySensor(
            coordinator, MagicMock(), "test_device", description
        )
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC


def test_error_sensors_are_not_diagnostic() -> None:
    """Spa/pool-filter errors surface as normal problem sensors."""
    coordinator = _make_coordinator()

    for description in (
        _SPA_ERRORS_SENSOR_DESCRIPTION,
        _POOL_FILTER_ERROR_SENSOR_DESCRIPTION,
    ):
        sensor = DeviceErrorsSensor(
            coordinator, MagicMock(), "test_device", description
        )
        assert sensor.entity_category is None


def test_pool_filter_change_sensor_is_not_diagnostic() -> None:
    """A change-required alert must not hide in the diagnostics section."""
    coordinator = _make_coordinator()
    sensor = PoolFilterChangeRequiredSensor(coordinator, MagicMock(), "test_device")
    assert sensor.entity_category is None
