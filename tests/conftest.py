"""Global fixtures for bestway integration."""

from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations."""
    yield


# This fixture is used to prevent HomeAssistant from attempting to create and dismiss persistent
# notifications. These calls would fail without this fixture since the persistent_notification
# integration is never loaded during a test.
@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with patch("homeassistant.components.persistent_notification.async_create"), patch(
        "homeassistant.components.persistent_notification.async_dismiss"
    ):
        yield


# Skips login requests to obtain a user token.
@pytest.fixture(name="bypass_auth")
def bypass_auth():
    """Skip authentication."""
    with patch("custom_components.bestway.bestway.api.BestwayApi.get_user_token"):
        yield


# Triggers an exception during user authentication.
@pytest.fixture(name="error_on_auth")
def error_auth():
    """Simulate error when retrieving data from API."""
    with patch(
        "custom_components.bestway.bestway.api.BestwayApi.get_user_token",
        side_effect=Exception,
    ):
        yield


# Skips fetching data.
@pytest.fixture(name="bypass_get_data")
def bypass_get_data_fixture():
    """Skip calls to get data from API."""
    with patch("custom_components.bestway.bestway.api.BestwayApi.fetch_data"), patch(
        "custom_components.bestway.bestway.api.BestwayApi.refresh_bindings"
    ):
        yield


# Triggers an exception when fetching data.
@pytest.fixture(name="error_on_get_data")
def error_get_data_fixture():
    """Simulate error when retrieving data from API."""
    with patch(
        "custom_components.bestway.bestway.api.BestwayApi.fetch_data",
        side_effect=Exception,
    ):
        yield
