"""Masking of credentials in log output.

People paste Home Assistant logs straight into public bug reports without
reading them, so anything that could be replayed against someone's Bestway
account - tokens, credentials, the signature that authenticates a request -
is masked before it ever reaches a log record.

Device ids are deliberately *not* masked. They are needed to tie a log line
to an entity when diagnosing a report, and are inert without an account
credential to go with them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "**REDACTED**"

# Matched case-insensitively against a mapping's keys, as a substring: the
# same value reaches us as "token", "user_token" and "accessToken" depending
# on which of the three cloud APIs produced it.
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "account",
        "auth",
        "email",
        "mac",
        "mobile",
        "nonce",
        "passcode",
        "password",
        "phone",
        "productkey",
        "product_key",
        "secret",
        "sign",
        "token",
        "uid",
        "username",
        "visitor",
    }
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Return a copy of `value` with sensitive entries masked.

    Recurses through mappings and sequences so a whole API response can be
    handed to a log call. Anything unrecognised is returned unchanged, which
    keeps this usable on the loosely-typed JSON these backends return.
    """
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [redact(item) for item in value]
    return value


def redact_text(value: str | None) -> str:
    """Mask a bare string that is sensitive because of where it came from.

    For values passed to a log call on their own, where there is no key to
    match on - a token or account name held in a local variable.
    """
    return REDACTED if value else ""
