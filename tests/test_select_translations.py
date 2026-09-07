"""Tests that every select option has a translation entry."""

import json
from pathlib import Path

from custom_components.bestway.select import _BUBBLES_OPTIONS

TRANSLATIONS = Path("custom_components/bestway/translations")


def _states(language: str) -> dict[str, str]:
    data = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    return data["entity"]["select"]["bubbles"]["state"]


def test_option_values_are_translation_slugs() -> None:
    """Option values must be slugs, or Home Assistant cannot look them up."""
    for option in _BUBBLES_OPTIONS.values():
        assert option.islower()
        assert option.replace("_", "").isalnum()


def test_every_option_is_translated_in_every_language() -> None:
    """A missing entry would surface the raw slug in the UI."""
    for language in sorted(p.stem for p in TRANSLATIONS.glob("*.json")):
        states = _states(language)
        for option in _BUBBLES_OPTIONS.values():
            assert option in states, f"{option} missing from {language}.json"
            assert states[option].strip()
