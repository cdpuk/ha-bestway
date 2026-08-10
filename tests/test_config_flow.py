"""Test bestway config flow."""

import threading
from collections.abc import Generator
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bestway.bestway.model import BestwayUserToken
from custom_components.bestway.const import (
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_USER_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

# Mock user input to the config flow
MOCK_USER_INPUT = {
    CONF_USERNAME: "test@example.org",
    CONF_PASSWORD: "P@asw0rd",
    CONF_API_ROOT: CONF_API_ROOT_EU,
}


# This fixture bypasses the actual setup of the integration
# since we only want to test the config flow. We test the
# actual functionality of the integration in other test modules.
@pytest.fixture(autouse=True)
def bypass_setup_fixture():
    """Prevent setup and unload.

    Config flow tests only exercise the flow logic, not the actual
    integration setup. Patching both prevents stray threads and teardown
    errors when HA tries to manage an entry that was never fully initialized.
    """
    with (
        patch(
            "custom_components.bestway.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.bestway.async_unload_entry",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def verify_cleanup() -> Generator[None]:
    """Override verify_cleanup to tolerate the _run_safe_shutdown_loop thread.

    The upstream fixture asserts no new threads exist after teardown, but
    shutdown_default_executor() spawns a short-lived daemon thread that
    races with this check. Config flow tests don't create real entities,
    so we just wait for any daemon threads to exit.
    """
    threads_before = frozenset(threading.enumerate())
    yield

    for thread in frozenset(threading.enumerate()) - threads_before:
        if thread.daemon:
            thread.join(timeout=2.0)


# Simulate a successful Gizwits config flow.
async def test_successful_config_flow(hass, bypass_get_data):
    """Test a successful Gizwits (V01) config flow."""
    # Initialize a config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check that the config flow shows backend selection as first step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select Gizwits backend
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "gizwits"}
    )

    # Check that we're routed to Gizwits auth
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "gizwits_auth"

    # Mock an authentication call that provides a token to keep hold of
    token = BestwayUserToken("foo", "t0k3n", 123)
    with patch(
        "custom_components.bestway.bestway.api.BestwayApi.get_user_token",
        return_value=token,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_USER_INPUT
        )

    # Verify entry created with correct data
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_USER_INPUT[CONF_USERNAME]
    assert result["data"]["backend"] == "gizwits"
    assert result["data"][CONF_USER_TOKEN] == token.user_token
    assert result["data"][CONF_USERNAME] == MOCK_USER_INPUT[CONF_USERNAME]
    assert result["result"]


# Simulate an exception during the authentication process
async def test_failed_config_flow(hass, error_on_auth):
    """Test a failed Gizwits config flow due to credential validation failure."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select Gizwits backend
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "gizwits"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "gizwits_auth"

    # Try to authenticate with credentials (will fail due to error_on_auth fixture)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_USER_INPUT
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unknown_connection_error"}


async def test_aws_iot_config_flow_routing(hass):
    """Test AWS IoT (V02) routing to auth step."""
    # Initialize config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Check backend selection shown
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    # Select AWS IoT backend
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )

    # Check routed to AWS IoT auth with QR and visitor_id options
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "aws_iot_auth"


async def test_aws_iot_auth_requires_qr_or_visitor(hass):
    """Test AWS IoT auth requires either QR or visitor_id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Select AWS IoT
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )

    # Submit with neither QR nor visitor_id
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    # Should show error
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "qr_or_visitor_required"


async def test_aws_iot_qr_validation(hass):
    """Test that unrecognised share input is rejected with a clear error.

    A code that is neither a legacy RW_Share_ token nor a valid new-style
    share link/id is routed to the Smart Home path and rejected there.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Select AWS IoT
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )

    # Submit invalid QR
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"qr_code": "INVALID_QR_123"},
    )

    # Should show a clear share-id error (no network call is made)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["qr_code"] == "invalid_share_id"


async def test_smart_home_share_url_creates_entry(hass):
    """A new-style share URL creates a Smart Home backend entry."""
    from custom_components.bestway.bestway.model import BestwayDevice
    from custom_components.bestway.const import BACKEND_SMART_HOME

    share_url = (
        "https://smart-spa-eu-app.bestwaycorp.com/app/appid/shareDevice/"
        "index.html?shareId=0123456789abcdef0123456789abcdef"
    )

    async def fake_refresh(self):
        self.devices = {
            "aabbccddeeff": BestwayDevice(
                protocol_version=2,
                device_id="aabbccddeeff",
                product_name="ULTRAFIT_AIRJET",
                alias="Toronto",
                mcu_soft_version="x",
                mcu_hard_version="x",
                wifi_soft_version="x",
                wifi_hard_version="x",
                is_online=True,
                backend=BACKEND_SMART_HOME,
                product_id="FTEW0E",
                product_series="ULTRAFIT_AIRJET",
            )
        }

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )

    with (
        patch(
            "custom_components.bestway.smart_home.api.SmartHomeApi.authenticate",
            return_value="test-token",
        ),
        patch(
            "custom_components.bestway.smart_home.api.SmartHomeApi.accept_share",
        ),
        patch(
            "custom_components.bestway.smart_home.api.SmartHomeApi.refresh_bindings",
            fake_refresh,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"region": "EU", "qr_code": share_url}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["backend"] == BACKEND_SMART_HOME
    assert result["data"]["region"] == "EU"
    # The share id must never be persisted in the config entry.
    assert "0123456789abcdef" not in str(result["data"])


async def test_smart_home_url_without_share_id(hass):
    """A share URL missing the shareId shows a clear error, makes no request."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "region": "EU",
            "qr_code": (
                "https://smart-spa-eu-app.bestwaycorp.com/app/x/shareDevice/index.html"
            ),
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["qr_code"] == "missing_share_id"


async def test_rw_share_still_uses_aws_backend(hass):
    """A legacy RW_Share_ code is still handled by the AWS IoT backend."""
    from custom_components.bestway.const import BACKEND_AWS_IOT

    async def fake_refresh(self):
        self.devices = {}  # no devices -> flow stops with no_devices_found

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"backend": "aws_iot"}
    )

    with (
        patch(
            "custom_components.bestway.aws_iot.api.AwsIotApi.authenticate",
            return_value="tok",
        ),
        patch(
            "custom_components.bestway.aws_iot.api.AwsIotApi.bind_qr_code",
            return_value={"device_id": "x"},
        ),
        patch(
            "custom_components.bestway.aws_iot.api.AwsIotApi.refresh_bindings",
            fake_refresh,
        ),
        patch(
            "custom_components.bestway.smart_home.api.SmartHomeApi.authenticate",
            side_effect=AssertionError("Smart Home path must not run for RW_Share_"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"region": "EU", "qr_code": "RW_Share_deadbeef"},
        )

    # Reaches the AWS IoT device-discovery stage (no devices in this test).
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "no_devices_found"
    _ = BACKEND_AWS_IOT


async def test_backend_selection_shows_both_options(hass):
    """Test backend selection displays both V01 and V02 options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    # Schema should have backend field with options
    schema_keys = list(result["data_schema"].schema.keys())
    assert any("backend" in str(key) for key in schema_keys)
