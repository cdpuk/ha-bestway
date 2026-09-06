"""Tests for log redaction."""

from custom_components.bestway.redact import REDACTED, redact, redact_text


def test_credentials_are_masked_at_any_depth():
    """Sensitive keys are masked wherever they appear in a response."""
    response = {
        "code": "200",
        "data": {"token": "real-token", "uid": "user-1", "expire": 3600},
    }

    assert redact(response) == {
        "code": "200",
        "data": {"token": REDACTED, "uid": REDACTED, "expire": 3600},
    }


def test_key_matching_is_case_insensitive_and_partial():
    """The three backends spell the same credential several ways."""
    masked = redact(
        {
            "accessToken": "a",
            "user_token": "b",
            "visitor_id": "c",
            "APP_SECRET": "d",
            "sign": "e",
        }
    )

    assert set(masked.values()) == {REDACTED}


def test_sequences_are_traversed():
    """A bindings response nests its devices inside a list."""
    bindings = {"devices": [{"passcode": "p", "mac": "m", "protoc": 1}]}

    assert redact(bindings) == {
        "devices": [{"passcode": REDACTED, "mac": REDACTED, "protoc": 1}]
    }


def test_device_ids_and_state_survive():
    """Redaction must not cost us the fields a bug report is diagnosed from.

    `did` identifies which device a log line belongs to, and shadow state is
    the payload we actually need to read.
    """
    payload = {
        "did": "f294cdeece1e11f0",
        "power_state": 1,
        "heater_state": 3,
        "water_temperature": 36,
    }

    assert redact(payload) == payload


def test_non_mapping_input_is_returned_unchanged():
    """These backends return loosely-typed JSON; nothing may raise."""
    assert redact("plain") == "plain"
    assert redact(7) == 7
    assert redact(None) is None


def test_redact_text_masks_only_non_empty():
    """An absent value should read as absent, not as a masked secret."""
    assert redact_text("token") == REDACTED
    assert redact_text("") == ""
    assert redact_text(None) == ""
