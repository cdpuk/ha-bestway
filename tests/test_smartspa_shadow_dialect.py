"""Write remapping must follow the gateway shadow dialect, not cached attrs.

v01_attrs_from_shadow copies Tnow/Tset onto V02 devices, so detecting dialect
from _raw_state.attrs after a poll would remap every write. Production always
polls before set_device_state.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.bestway.smartspa.api import SmartSpaApi


@pytest.fixture
def mock_session():
    """Create mock aiohttp ClientSession."""
    session = AsyncMock()
    session.post = MagicMock()
    session.request = MagicMock()
    return session


@pytest.fixture
def api(mock_session):
    """Create a SmartSpaApi with a valid token and one known device."""
    client = SmartSpaApi(
        session=mock_session,
        account="user@example.com",
        password="hunter2",
        api_base="https://smart-spa-eu-app.bestwaycorp.com",
        token="valid_token",
    )
    client._routing["6879c4d585ab"] = ("F12D9Q", "6879c4d585ab")
    return client


async def test_v02_poll_does_not_remap_writes(api):
    """F12D9Q / FTEW0E keep filter_state / temperature_setting after a poll."""
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": {
                "water_temperature": 33,
                "temperature_setting": 39,
                "filter_state": 2,
                "power_state": 1,
                "ConnectType": "online",
            },
        }
    )
    await api.fetch_data()
    api._request = AsyncMock(return_value={"code": "200", "data": True})

    await api.set_filter("6879c4d585ab", True)
    await api.set_target_temperature("6879c4d585ab", 36)

    sent = [json.loads(call[0][2]["data"]) for call in api._request.call_args_list]
    assert sent[0] == {"filter_state": 1}
    assert sent[1] == {"temperature_setting": 36}


async def test_v01_poll_remaps_writes(api):
    """A Tnow/Tset shadow remaps writes to V01 names."""
    api._request = AsyncMock(
        return_value={
            "code": "200",
            "data": {
                "Tnow": 38,
                "Tset": 40,
                "Tunit": 0,
                "heat": 3,
                "filter": 2,
                "power": 1,
                "ConnectType": "online",
            },
        }
    )
    await api.fetch_data()
    api._request = AsyncMock(return_value={"code": "200", "data": True})

    await api.set_filter("6879c4d585ab", True)
    await api.set_target_temperature("6879c4d585ab", 36)

    sent = [json.loads(call[0][2]["data"]) for call in api._request.call_args_list]
    assert sent[0] == {"filter": 2}
    assert sent[1] == {"Tset": 36}
