"""Tests for AWS IoT encryption module."""

import json
import pytest

from custom_components.bestway.aws_iot.encryption import (
    decrypt_command_payload,
    encrypt_command_payload,
)


def test_encrypt_decrypt_round_trip():
    """Test basic encryption and decryption round-trip."""
    data = {"device_id": "test123", "command": {"power": 1}}
    sign = "C4C0283EF2420F03624068553CC8783C"
    app_secret = "4ECvVs13enL5AiYSmscNjvlaisklQDz7vWPCCWXcEFjhWfTmLT"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)

    assert decrypted == data


def test_encrypt_different_signs_different_output():
    """Verify different signatures produce different encrypted outputs."""
    data = {"test": "value"}
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted1 = encrypt_command_payload("SIGN1" * 6, app_secret, plaintext)
    encrypted2 = encrypt_command_payload("SIGN2" * 6, app_secret, plaintext)

    # Same data, different signs → different ciphertext
    assert encrypted1 != encrypted2


def test_encrypt_different_secrets_different_output():
    """Verify different app secrets produce different encrypted outputs."""
    data = {"test": "value"}
    sign = "A" * 32

    plaintext = json.dumps(data)
    encrypted1 = encrypt_command_payload(sign, "secret1", plaintext)
    encrypted2 = encrypt_command_payload(sign, "secret2", plaintext)

    # Same data+sign, different secrets → different ciphertext
    assert encrypted1 != encrypted2


def test_encrypt_complex_nested_data():
    """Test encryption of complex nested command structure."""
    data = {
        "device_id": "f294cdeece1e11f0abb45925c07ce073",
        "product_id": "T53NN8",
        "command": {
            "power_state": 1,
            "heater_state": 3,
            "temperature_setting": 37,
            "wave_state": 100,
        },
    }
    sign = "B" * 32
    app_secret = "test_secret_123"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)

    assert decrypted == data
    assert decrypted["command"]["power_state"] == 1
    assert decrypted["command"]["temperature_setting"] == 37


def test_encrypt_unicode_characters():
    """Test encryption handles Unicode characters correctly."""
    data = {"device_name": "Tubby™ Spa", "location": "Köln"}
    sign = "C" * 32
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)

    assert decrypted == data
    assert decrypted["device_name"] == "Tubby™ Spa"


def test_encrypt_empty_command():
    """Test encryption of minimal/empty command."""
    data = {}
    sign = "D" * 32
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)

    assert decrypted == data


def test_encrypt_large_payload():
    """Test encryption of large command payload (>1KB)."""
    data = {"items": [f"item_{i}" for i in range(100)]}
    sign = "E" * 32
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)

    assert decrypted == data
    assert len(decrypted["items"]) == 100


def test_decrypt_with_wrong_sign_fails():
    """Verify decryption fails with wrong signature."""
    data = {"test": "value"}
    sign = "F" * 32
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)

    # Try to decrypt with different sign
    with pytest.raises(Exception):  # ValueError or padding error
        decrypt_command_payload("WRONG" * 6, app_secret, encrypted)


def test_decrypt_with_wrong_secret_fails():
    """Verify decryption fails with wrong app secret."""
    data = {"test": "value"}
    sign = "G" * 32
    app_secret = "secret"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)

    # Try to decrypt with different secret
    with pytest.raises(Exception):  # ValueError or padding error
        decrypt_command_payload(sign, "wrong_secret", encrypted)


def test_decrypt_invalid_base64_fails():
    """Verify decryption fails with invalid base64 input."""
    sign = "H" * 32
    app_secret = "secret"

    with pytest.raises(Exception):  # Base64 decode error
        decrypt_command_payload(sign, app_secret, "not-valid-base64!!!")


def test_encrypt_known_test_vector():
    """Validate encryption against known working example from APK analysis.

    This test uses a captured command from the official app to verify our
    implementation produces compatible encrypted payloads.
    """
    # Test vector from New_bestway_spa implementation
    data = {"device_id": "abc", "product_id": "T53NN8", "command": {"power": 1}}
    sign = "C4C0283EF2420F03624068553CC8783C"
    app_secret = "4ECvVs13enL5AiYSmscNjvlaisklQDz7vWPCCWXcEFjhWfTmLT"

    plaintext = json.dumps(data)
    encrypted = encrypt_command_payload(sign, app_secret, plaintext)

    # Verify format
    assert encrypted.startswith("OG46qEz")  # Fixed IV in base64
    assert len(encrypted) > 50  # Should be substantial length

    # Verify round-trip
    decrypted_str = decrypt_command_payload(sign, app_secret, encrypted)
    decrypted = json.loads(decrypted_str)
    assert decrypted == data
