"""AES-256-CBC encryption for AWS IoT backend commands.

This module implements the Bestway-specific encryption algorithm discovered through
reverse engineering of the official Bestway Smart Spa Android app.

Algorithm Details:
- Cipher: AES-256-CBC with PKCS7 padding
- Key Derivation: SHA-256("{sign},{app_secret}")[:32] as UTF-8 bytes
- IV: Fixed 16-byte array (hardcoded in official app)
- Output: Base64(IV + ciphertext)

Source: Decompiled from com/rongwei/library/utils/AESEncrypt.java
Reference: layzspa-aws-iot/bestway_spa_client.py
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad

    HAS_PYCRYPTODOME = True
except ImportError:
    HAS_PYCRYPTODOME = False
    _LOGGER.error(
        "pycryptodome not installed - AWS IoT encryption unavailable. "
        "Install with: pip install pycryptodome>=3.20.0"
    )

# Fixed IV from decompiled APK (never changes)
# Source: AESEncrypt.java in com.rongwei.library.utils
FIXED_IV = bytes(
    [56, 110, 58, 168, 76, 255, 94, 159, 237, 215, 171, 181, 150, 40, 74, 166]
)


def encrypt_command_payload(sign: str, app_secret: str, plaintext: str) -> str:
    """Encrypt command payload using Bestway's AES-256-CBC scheme.

    EXACT copy of working implementation from New_bestway_spa/encryption.py
    Signature: (sign, app_secret, plaintext_string) - NOT (data, sign, app_secret)!

    Args:
        sign: MD5 signature from current request (uppercase hex)
        app_secret: APP_SECRET constant (same for all users, from APK)
        plaintext: Command payload as JSON string (already serialized!)

    Returns:
        Base64-encoded encrypted payload: Base64(IV + ciphertext)

    Raises:
        RuntimeError: If pycryptodome is not installed
    """
    if not HAS_PYCRYPTODOME:
        raise RuntimeError(
            "pycryptodome not installed. "
            "Install with: pip install pycryptodome>=3.20.0"
        )

    # Key derivation: SHA-256(f"{sign},{app_secret}")[:32] as UTF-8 bytes
    key_material = f"{sign},{app_secret}".encode("utf-8")
    key_hex = hashlib.sha256(key_material).hexdigest()[:32]
    key = key_hex.encode("utf-8")  # 32 bytes

    # Encrypt plaintext string with AES-256-CBC
    cipher = AES.new(key, AES.MODE_CBC, FIXED_IV)
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    ciphertext = cipher.encrypt(padded)

    # Return Base64(IV + ciphertext)
    result = base64.b64encode(FIXED_IV + ciphertext).decode("utf-8")

    _LOGGER.debug("Encrypted payload (first 20 chars): %s...", result[:20])
    return result


def decrypt_command_payload(sign: str, app_secret: str, ciphertext: str) -> str:
    """Decrypt command payload (inverse of encrypt_command_payload).

    EXACT copy of reference signature and behavior.

    Args:
        sign: Same MD5 signature used for encryption
        app_secret: Same APP_SECRET constant
        ciphertext: Base64-encoded encrypted data

    Returns:
        Decrypted plaintext string

    Raises:
        RuntimeError: If pycryptodome is not installed
    """
    if not HAS_PYCRYPTODOME:
        raise RuntimeError(
            "pycryptodome not installed. "
            "Install with: pip install pycryptodome>=3.20.0"
        )

    # Derive key same way as encryption
    key_material = f"{sign},{app_secret}".encode("utf-8")
    key_hex = hashlib.sha256(key_material).hexdigest()[:32]
    key = key_hex.encode("utf-8")

    # Decode base64 and extract IV + ciphertext
    data = base64.b64decode(ciphertext)
    iv = data[:16]
    ct = data[16:]

    # Decrypt
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_plaintext = cipher.decrypt(ct)
    plaintext = unpad(padded_plaintext, AES.block_size)

    return plaintext.decode("utf-8")
