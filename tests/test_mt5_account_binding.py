from __future__ import annotations

import base64
import hashlib
import hmac
import inspect

import pytest

from ops.mt5_mcp import account_binding

TEST_KEY = bytes(range(32))
TEST_KEY_ID = "audit-2026-01"


def test_v1_canonical_message_uses_domain_and_byte_lengths() -> None:
    login = b"12345678"
    server = b"XMGlobal-MT5 10"
    expected = (
        b"WOLF15\x00ACCOUNT_BINDING\x00V1\x00"
        + len(login).to_bytes(4, "big")
        + login
        + len(server).to_bytes(4, "big")
        + server
    )

    assert account_binding.canonical_message(12345678, "XMGlobal-MT5 10") == expected


def test_identifier_is_full_domain_separated_hmac_sha256() -> None:
    canonical = account_binding.canonical_message(12345678, "XMGlobal-MT5 10")
    digest = hmac.new(TEST_KEY, canonical, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    result = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=12345678,
        server="XMGlobal-MT5 10",
    )

    assert result == f"w15ab:v1:{TEST_KEY_ID}:{encoded}"
    assert len(encoded) == 43
    assert "=" not in result
    assert account_binding.identifier_key_id(result) == TEST_KEY_ID


@pytest.mark.parametrize("login", [0, -1, True, "", "012345", "+123", "123 ", 1 << 63])
def test_login_must_be_positive_canonical_ascii_decimal(login: object) -> None:
    with pytest.raises(account_binding.AccountBindingError):
        account_binding.canonical_login(login)


@pytest.mark.parametrize(
    "server",
    ["", " Broker-Demo", "Broker-Demo ", "Broker\nDemo", "Bróker-Demo", "x" * 129],
)
def test_server_is_exact_case_printable_ascii_with_bounded_byte_length(server: str) -> None:
    with pytest.raises(account_binding.AccountBindingError):
        account_binding.canonical_server(server)


def test_server_case_is_not_normalized() -> None:
    upper = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=12345678,
        server="Broker-Demo",
    )
    lower = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=12345678,
        server="broker-demo",
    )

    assert upper != lower
    assert not account_binding.identifiers_match(upper, lower)


def test_secret_key_environment_encoding_is_unpadded_base64url_and_256_bit_minimum() -> None:
    encoded = base64.urlsafe_b64encode(TEST_KEY).rstrip(b"=").decode("ascii")
    assert account_binding.decode_secret_key(encoded) == TEST_KEY

    with pytest.raises(account_binding.AccountBindingError, match="ACCOUNT_BINDING_KEY_TOO_SHORT"):
        account_binding.decode_secret_key("YQ")
    with pytest.raises(account_binding.AccountBindingError, match="ACCOUNT_BINDING_KEY_ENCODING_INVALID"):
        account_binding.decode_secret_key(encoded + "=")


def test_comparison_uses_constant_time_primitive_and_rejects_malformed_identifiers() -> None:
    value = account_binding.identifier(
        secret_key=TEST_KEY,
        key_id=TEST_KEY_ID,
        login=12345678,
        server="Broker-Demo",
    )

    assert account_binding.identifiers_match(value, value)
    assert not account_binding.identifiers_match(value, "sha256:" + "a" * 64)
    assert "hmac.compare_digest" in inspect.getsource(account_binding.identifiers_match)
