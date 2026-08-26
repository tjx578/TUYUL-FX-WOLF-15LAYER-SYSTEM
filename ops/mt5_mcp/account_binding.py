"""Canonical, non-reversible Wolf15 account-binding identifiers.

The HMAC key is audit-local authority.  It is never embedded in an identifier,
report, database row, or log message.  Database and direct-MT5 identifiers are
comparable only when they use this exact versioned contract and key id.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from typing import Final

SCHEME: Final = "w15-account-binding"
VERSION: Final = "v1"
ALGORITHM: Final = "HMAC-SHA-256"
DOMAIN: Final = b"WOLF15\x00ACCOUNT_BINDING\x00V1\x00"
KEY_ENV: Final = "WOLF15_ACCOUNT_BINDING_KEY_B64URL"
KEY_ID_ENV: Final = "WOLF15_ACCOUNT_BINDING_KEY_ID"
DATABASE_SOURCE: Final = "EXECUTOR_INSTANCE_ACCOUNT_ID"
MINIMUM_KEY_BYTES: Final = 32
MAXIMUM_LOGIN: Final = (1 << 63) - 1
MAXIMUM_SERVER_BYTES: Final = 128

_LOGIN_RE: Final = re.compile(r"[1-9][0-9]*\Z")
_KEY_ID_RE: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")
_IDENTIFIER_RE: Final = re.compile(r"w15ab:v1:([a-z0-9][a-z0-9._-]{0,31}):([A-Za-z0-9_-]{43})\Z")


class AccountBindingError(ValueError):
    """Fail-closed validation error carrying a stable, non-secret code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_login(value: object) -> bytes:
    """Return a positive, no-leading-zero ASCII decimal MT5 login."""

    if isinstance(value, bool):
        raise AccountBindingError("ACCOUNT_BINDING_LOGIN_INVALID")
    login = str(value)
    if not _LOGIN_RE.fullmatch(login):
        raise AccountBindingError("ACCOUNT_BINDING_LOGIN_INVALID")
    if int(login) > MAXIMUM_LOGIN:
        raise AccountBindingError("ACCOUNT_BINDING_LOGIN_OUT_OF_RANGE")
    return login.encode("ascii")


def canonical_server(value: object) -> bytes:
    """Return an exact-case, printable ASCII broker server name."""

    if not isinstance(value, str) or value != value.strip():
        raise AccountBindingError("ACCOUNT_BINDING_SERVER_INVALID")
    try:
        server = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AccountBindingError("ACCOUNT_BINDING_SERVER_NON_ASCII") from exc
    if not server or len(server) > MAXIMUM_SERVER_BYTES:
        raise AccountBindingError("ACCOUNT_BINDING_SERVER_INVALID")
    if any(byte < 0x20 or byte > 0x7E for byte in server):
        raise AccountBindingError("ACCOUNT_BINDING_SERVER_INVALID")
    return server


def validate_key_id(value: object) -> str:
    """Validate the public key-version identifier."""

    if not isinstance(value, str) or not _KEY_ID_RE.fullmatch(value):
        raise AccountBindingError("ACCOUNT_BINDING_KEY_ID_INVALID")
    return value


def decode_secret_key(value: str) -> bytes:
    """Decode an unpadded base64url key and enforce 256-bit minimum entropy."""

    if not value or "=" in value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise AccountBindingError("ACCOUNT_BINDING_KEY_ENCODING_INVALID")
    padding = "=" * (-len(value) % 4)
    try:
        key = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AccountBindingError("ACCOUNT_BINDING_KEY_ENCODING_INVALID") from exc
    if len(key) < MINIMUM_KEY_BYTES:
        raise AccountBindingError("ACCOUNT_BINDING_KEY_TOO_SHORT")
    return key


def canonical_message(login: object, server: object) -> bytes:
    """Build the length-delimited v1 HMAC message using byte lengths."""

    login_bytes = canonical_login(login)
    server_bytes = canonical_server(server)
    return (
        DOMAIN + len(login_bytes).to_bytes(4, "big") + login_bytes + len(server_bytes).to_bytes(4, "big") + server_bytes
    )


def identifier(*, secret_key: bytes, key_id: object, login: object, server: object) -> str:
    """Derive the full v1 account-binding identifier."""

    if len(secret_key) < MINIMUM_KEY_BYTES:
        raise AccountBindingError("ACCOUNT_BINDING_KEY_TOO_SHORT")
    validated_key_id = validate_key_id(key_id)
    digest = hmac.new(secret_key, canonical_message(login, server), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"w15ab:v1:{validated_key_id}:{encoded}"


def identifier_key_id(value: object) -> str:
    """Validate an identifier and return its public key id."""

    if not isinstance(value, str):
        raise AccountBindingError("ACCOUNT_BINDING_IDENTIFIER_INVALID")
    match = _IDENTIFIER_RE.fullmatch(value)
    if match is None:
        raise AccountBindingError("ACCOUNT_BINDING_IDENTIFIER_INVALID")
    return match.group(1)


def identifiers_match(left: object, right: object) -> bool:
    """Validate and compare full identifiers in constant time."""

    try:
        left_value = str(left)
        right_value = str(right)
        identifier_key_id(left_value)
        identifier_key_id(right_value)
    except AccountBindingError:
        return False
    return hmac.compare_digest(left_value.encode("ascii"), right_value.encode("ascii"))
