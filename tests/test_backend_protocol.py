"""Every backend API client must satisfy the BackendApi protocol.

A cheap regression guard so a new backend (or a signature drift in an
existing one) fails here rather than at a coordinator/entity call site.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.bestway.aws_iot.api import AwsIotApi
from custom_components.bestway.backend import BackendApi
from custom_components.bestway.bestway.api import BestwayApi
from custom_components.bestway.smartspa.api import SmartSpaApi


@pytest.fixture
def backends():
    """One lightweight instance of each backend client."""
    session = MagicMock()
    return [
        BestwayApi(session, "token", "https://example.invalid"),
        AwsIotApi(session, "visitor-id"),
        SmartSpaApi(session, "account", "password", "https://example.invalid"),
    ]


def test_backends_satisfy_protocol(backends):
    """Each client is a structural instance of BackendApi."""
    for api in backends:
        assert isinstance(api, BackendApi)
