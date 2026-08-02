"""Static safety contract for the MT5 SHADOW executor source."""

from __future__ import annotations

import json
import re
from pathlib import Path

EA_SOURCE = Path(__file__).resolve().parents[1] / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
SIGNED_VECTOR = EA_SOURCE.parent / "test_vectors" / "signed_envelope_v2.json"


def _source() -> str:
    return EA_SOURCE.read_text(encoding="utf-8")


def _on_init(source: str) -> str:
    match = re.search(r"\bint\s+OnInit\s*\(\s*\)(.*?)\bvoid\s+OnTimer\s*\(", source, re.DOTALL)
    assert match is not None, "EA source must define OnInit before OnTimer"
    return match.group(1)


def _poll_one_command(source: str) -> str:
    match = re.search(r"\bvoid\s+PollOneCommand\s*\(\s*\)(.*?)\bint\s+OnInit\s*\(", source, re.DOTALL)
    assert match is not None, "EA source must define PollOneCommand before OnInit"
    return match.group(1)


def test_shadow_executor_binds_the_runtime_mt5_login() -> None:
    on_init = _on_init(_source())

    assert "AccountInfoInteger(ACCOUNT_LOGIN)" in on_init
    assert re.search(r"actual_account_id\s*!=\s*InpExpectedAccountId", on_init)
    assert "return INIT_FAILED;" in on_init


def test_shadow_executor_has_no_broker_mutation_calls() -> None:
    source = _source()

    forbidden_calls = (
        "OrderSend",
        "OrderSendAsync",
        "OrderCheck",
        "PositionOpen",
        "PositionClose",
        "PositionModify",
        "OrderDelete",
        "OrderModify",
    )
    for function in forbidden_calls:
        assert re.search(rf"\b{function}\s*\(", source) is None


def test_shadow_executor_rejects_execution_enabled() -> None:
    source = _source()
    on_init = _on_init(source)

    assert "input bool   InpExecutionEnabled    = false;" in source
    assert re.search(r"if\s*\(\s*InpExecutionEnabled\s*\)", on_init)
    assert "return INIT_PARAMETERS_INCORRECT;" in on_init


def test_invalid_credentials_are_diagnosed_without_printing_values() -> None:
    on_init = _on_init(_source())

    assert "executor_id_length = StringLen(InpExecutorId)" in on_init
    assert "executor_token_length = StringLen(InpExecutorToken)" in on_init
    assert "login_hash_length = StringLen(InpLoginHash)" in on_init
    assert "executor_id_length=%d token_length=%d" in on_init
    assert "login_hash_length=%d" in on_init
    assert 'PrintFormat("%s", InpExecutorToken)' not in on_init
    assert 'PrintFormat("%s", InpLoginHash)' not in on_init


def test_signed_wire_credentials_are_required_without_logging_values() -> None:
    source = _source()
    on_init = _on_init(source)

    assert 'input string InpCommandVerificationKeyId = "";' in source
    assert 'input string InpCommandVerificationKey   = "";' in source
    assert 'TaggedHexToBytes(InpCommandVerificationKey, "hex:", 32, verification_key)' in on_init
    assert "IsSafeWireIdentifier(InpCommandVerificationKeyId)" in on_init
    assert "verification_key_id_length=%d" in on_init
    assert "verification_key_length=%d" in on_init
    assert 'PrintFormat("%s", InpCommandVerificationKey)' not in on_init


def test_signed_wire_crypto_self_test_matches_the_public_golden_vector() -> None:
    source = _source()
    vector = json.loads(SIGNED_VECTOR.read_text(encoding="utf-8"))

    expected_constants = {
        "W15_GOLDEN_EXECUTOR_ID": vector["executor_id"],
        "W15_GOLDEN_KEY_ID": vector["key_id"],
        "W15_GOLDEN_KEY_HEX": vector["verification_key_hex"],
        "W15_GOLDEN_PAYLOAD_B64": vector["payload_b64"],
        "W15_GOLDEN_PAYLOAD_SHA256": vector["payload_sha256"],
        "W15_GOLDEN_SIGNATURE": vector["signature"],
    }
    for name, value in expected_constants.items():
        assert f'#define {name} "{value}"' in source

    assert "CryptEncode(CRYPT_HASH_SHA256" in source
    assert "CryptDecode(CRYPT_BASE64" in source
    assert "HmacSha256Bytes" in source
    assert "ConstantTimeBytesEqual" in source
    assert 'preimage + "x"' in source
    assert "RunSignedWireCryptoSelfTest()" in _on_init(source)
    assert re.search(
        r"if\s*\(\s*!RunSignedWireCryptoSelfTest\(\)\s*\).*?return INIT_FAILED;", _on_init(source), re.DOTALL
    )


def test_poll_verifies_frozen_wire_bytes_before_parsing_command() -> None:
    source = _source()
    poll = _poll_one_command(source)

    verification = poll.index("VerifySignedEnvelope(")
    validation = poll.index("ValidateShadowCommand(command_json, reason)")
    report = poll.index("SendShadowReport(command_json, claim_token, request_hash, accepted, reason)")
    assert verification < validation < report
    assert "ValidateShadowCommand(claim_response" not in poll
    assert "SendShadowReport(claim_response" not in poll
    assert "SHADOW_PREFLIGHT_PASSED_SIGNATURE_PRESENT_NOT_YET_LOCALLY_VERIFIED" not in source
    assert "SHADOW_PREFLIGHT_PASSED_SIGNATURE_VERIFIED" in source


def test_invalid_signed_wire_is_quarantined_without_reporting() -> None:
    poll = _poll_one_command(_source())
    failure = re.search(
        r"if\s*\(\s*!VerifySignedEnvelope\(.*?\)\s*\)\s*\{(.*?)\}",
        poll,
        re.DOTALL,
    )
    assert failure is not None
    failure_body = failure.group(1)
    assert "g_quarantined_command_id = command_id;" in failure_body
    assert 'AppendLedger(command_id, "QUARANTINED", reason);' in failure_body
    assert "SendShadowReport" not in failure_body
    assert "return;" in failure_body
    assert "command_id == g_quarantined_command_id" in poll


def test_signed_envelope_verifier_binds_hash_command_and_executor() -> None:
    source = _source()

    assert 'JsonObject(response_json, "signed_envelope")' in source
    assert "request_hash != payload_sha256" in source
    assert 'TaggedHexToBytes(payload_sha256, "sha256:", 32, expected_payload_hash)' in source
    assert 'JsonValue(command_json, "command_id") != expected_command_id' in source
    assert 'JsonValue(command_json, "executor_id") != InpExecutorId' in source
    assert 'StringFind(signature, "base64url:") != 0' in source
    signature_check = source.index("!ConstantTimeBytesEqual(signature_bytes, calculated_signature)")
    payload_decode = source.index("CharArrayToString(payload_bytes")
    command_parse = source.index('JsonValue(command_json, "command_id")')
    assert signature_check < payload_decode < command_parse
