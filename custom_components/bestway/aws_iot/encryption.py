"""AES-256-CBC encryption for AWS IoT backend commands.

This module implements the Bestway-specific encryption algorithm discovered through
reverse engineering of the official Bestway Smart Spa Android app.

Algorithm Details:
- Cipher: AES-256-CBC with PKCS7 padding
- Key Derivation: SHA-256("{sign},{app_secret}")[:32] as UTF-8 bytes
- IV: Fixed 16-byte array (hardcoded in official app)
- Output: Base64(IV + ciphertext)

Source: Decompiled from com/rongwei/library/utils/AESEncrypt.java
"""

from __future__ import annotations

import base64
import hashlib
import logging

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

_LOGGER = logging.getLogger(__name__)

# Fixed IV from decompiled APK (never changes)
# Source: AESEncrypt.java in com.rongwei.library.utils
FIXED_IV = bytes(
    [56, 110, 58, 168, 76, 255, 94, 159, 237, 215, 171, 181, 150, 40, 74, 166]
)


def encrypt_command_payload(sign: str, app_secret: str, plaintext: str) -> str:
    """Encrypt an already-serialized JSON command payload with Bestway's
    AES-256-CBC scheme, returning Base64(IV + ciphertext).

    Argument order is (sign, app_secret, plaintext) - `sign` is the
    request's own MD5 signature (uppercase hex), used as key material
    alongside `app_secret`, not the data being encrypted.
    """
    # Key derivation: SHA-256(f"{sign},{app_secret}")[:32] as UTF-8 bytes
    key_material = f"{sign},{app_secret}".encode()
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
    """Decrypt a Base64(IV + ciphertext) payload back to plaintext - the
    inverse of `encrypt_command_payload`, with the same `sign` and
    `app_secret` used to encrypt it.
    """
    # Derive key same way as encryption
    key_material = f"{sign},{app_secret}".encode()
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

    return str(plaintext.decode("utf-8"))
