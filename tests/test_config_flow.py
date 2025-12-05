"""Test bestway config flow."""

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bestway.bestway.model import BestwayUserToken
from custom_components.bestway.const import (
    CONF_API_ROOT,
    CONF_API_ROOT_EU,
    CONF_PASSWORD,
    CONF_UID,
    CONF_USER_TOKEN,
    CONF_USER_TOKEN_EXPIRY,
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
    """Prevent setup."""
    with patch(
        "custom_components.bestway.async_setup_entry",
        return_value=True,
    ):
        yield


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
    """Test QR code format validation."""
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

    # Should show QR format error
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["qr_code"] == "invalid_qr_format"


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
