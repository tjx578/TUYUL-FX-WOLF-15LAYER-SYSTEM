"""Static safety contract for the MT5 SHADOW executor source."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

EA_SOURCE = Path(__file__).resolve().parents[1] / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
PROBE_SOURCE = EA_SOURCE.parent / "Wolf15_Step1B_SymbolProbe.mq5"
SIGNED_VECTOR = EA_SOURCE.parent / "test_vectors" / "signed_envelope_v2.json"
BROKER_MAP = EA_SOURCE.parent / "broker_maps" / "xmglobal-mt5-10.csv"
PAIR_CONFIG = EA_SOURCE.parents[2] / "config" / "pairs.yaml"


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


def _between_functions(source: str, start: str, end: str) -> str:
    pattern = rf"\b(?:bool|int|void|string)\s+{re.escape(start)}\s*\(.*?(?=\b(?:bool|int|void|string)\s+{re.escape(end)}\s*\()"
    match = re.search(pattern, source, re.DOTALL)
    assert match is not None, f"EA source must define {start} before {end}"
    return match.group(0)


def _mql_string_array(source: str, name: str) -> list[str]:
    match = re.search(
        rf"string\s+{re.escape(name)}\s*\[[^]]+\]\s*=\s*\{{(.*?)\}};",
        source,
        re.DOTALL,
    )
    assert match is not None, f"EA source must define {name}"
    return re.findall(r'"([A-Z0-9._-]+)"', match.group(1))


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


def test_shadow_executor_uses_one_audited_30_symbol_universe() -> None:
    source = _source()
    with BROKER_MAP.open(newline="", encoding="utf-8") as handle:
        broker_rows = list(csv.DictReader(handle))
    configured = re.findall(r'symbol:\s*"([A-Z0-9._-]+)"', PAIR_CONFIG.read_text(encoding="utf-8"))
    canonical = _mql_string_array(source, "W15_CANONICAL_SYMBOLS")
    broker = _mql_string_array(source, "W15_BROKER_SYMBOLS")

    assert len(broker_rows) == 30
    assert len(canonical) == len(set(canonical)) == 30
    assert len(broker) == len(set(broker)) == 30
    assert canonical == configured
    assert list(zip(canonical, broker, strict=True)) == [
        (row["canonical_symbol"], row["broker_symbol"]) for row in broker_rows
    ]
    assert _mql_string_array(PROBE_SOURCE.read_text(encoding="utf-8"), "CanonicalSymbols") == canonical
    assert ("XAUUSD", "GOLD") in zip(canonical, broker, strict=True)
    assert ("XAGUSD", "SILVER") in zip(canonical, broker, strict=True)
    assert "InpCanonicalSymbol" not in source
    assert "InpBrokerSymbol" not in source


def test_multi_symbol_commands_are_bound_before_capability_lookup() -> None:
    source = _source()
    validation = _between_functions(source, "ValidateShadowCommand", "BlockPendingRecovery")
    heartbeat = _between_functions(source, "SendHeartbeat", "IsStepCompatible")
    initialization = _between_functions(source, "InitializeSymbolUniverse", "BuildSymbolsJson")

    pair_check = validation.index("SymbolPairIndex(canonical_symbol, broker_symbol)")
    select = validation.index("SymbolSelect(broker_symbol, true)")
    volume = validation.index("SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN)")
    assert pair_check < select < volume
    assert "SYMBOL_BINDING_MISMATCH" in validation
    assert "SYMBOL_RUNTIME_NOT_READY" in validation
    assert "for(int index = 0; index < W15_SYMBOL_COUNT; index++)" in initialization
    assert "SYMBOL_UNIVERSE_DUPLICATE" in initialization
    assert "SYMBOL_TRADE_MODE_FULL" in initialization
    assert "string symbols_json = BuildSymbolsJson();" in heartbeat
    assert "if(StringLen(symbols_json) == 0)" in heartbeat


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


def test_pending_report_is_atomically_persisted_before_transport() -> None:
    source = _source()
    save = _between_functions(source, "SavePendingReport", "LoadPendingReport")
    send = _between_functions(source, "SendShadowReport", "PollOneCommand")

    assert "FILE_WRITE | FILE_BIN | FILE_ANSI" in save
    assert "FileFlush(handle);" in save
    assert "FileClose(handle);" in save
    assert "FileMove(temporary_path, 0, PendingReportPath(), FILE_REWRITE)" in save
    assert "ComputePendingIntegrityTag(pending, pending.integrity_tag)" in save
    assert send.index("SavePendingReport(pending, storage_error)") < send.index("PostPendingReport(pending, response)")
    assert "pending.report_id = MakeUuid();" in send
    assert "pending.report_body = StringFormat(" in send


def test_restart_drill_holds_only_after_the_pending_report_is_durable() -> None:
    source = _source()
    send = _between_functions(source, "SendShadowReport", "PollOneCommand")

    assert "input bool   InpRestartDrillHoldAfterDurableSave = false;" in source
    save = send.index("SavePendingReport(pending, storage_error)")
    hold = send.index("if(InpRestartDrillHoldAfterDurableSave)")
    post = send.index("PostPendingReport(pending, response)")
    assert save < hold < post
    assert 'AppendLedger(command_id, "RESTART_DRILL_ARMED",' in send
    assert "g_recovery_blocked = true;" in send
    assert "ClearPendingReport" not in send[hold:post]


def test_restart_reconciles_server_truth_before_resending() -> None:
    source = _source()
    recover = _between_functions(source, "RecoverPendingReport", "SendShadowReport")
    acknowledgement = _between_functions(source, "HandlePendingPostResult", "ReclaimPendingReport")

    status = recover.index('"/api/v1/executors/" + InpExecutorId +')
    post = recover.index("PostPendingReport(pending, report_response)")
    assert status < post
    assert 'JsonBool(status_response, "terminal")' in recover
    assert 'JsonObject(status_response, "latest_report")' in recover
    assert 'JsonValue(latest_report, "request_hash") != pending.request_hash' in recover
    assert "FinalizePendingReport(pending, outcome)" in recover
    assert '!JsonBool(response, "accepted")' in acknowledgement
    assert 'JsonValue(response, "command_id") != pending.command_id' in acknowledgement


def test_reclaim_rotates_the_token_durably_before_resend() -> None:
    source = _source()
    reclaim = _between_functions(source, "ReclaimPendingReport", "RecoverPendingReport")
    recover = _between_functions(source, "RecoverPendingReport", "SendShadowReport")

    token_update = reclaim.index("pending.claim_token = new_claim_token;")
    durable_update = reclaim.index("SavePendingReport(pending, reason)")
    assert token_update < durable_update
    assert "VerifySignedEnvelope(claim_response" in reclaim
    reclaim_call = recover.index("ReclaimPendingReport(pending)")
    retry_post = recover.rindex("PostPendingReport(pending, report_response)")
    assert reclaim_call < retry_post


def test_pending_state_is_bound_and_blocks_new_command_polling() -> None:
    source = _source()
    on_init = _on_init(source)
    validation = _between_functions(source, "ValidateShadowCommand", "BlockPendingRecovery")
    timer = re.search(r"\bvoid\s+OnTimer\s*\(\s*\)(.*?)\bvoid\s+OnDeinit\s*\(", source, re.DOTALL)
    assert timer is not None
    on_timer = timer.group(1)

    assert "pending.executor_id != InpExecutorId" in source
    assert "pending.account_id != InpExpectedAccountId" in source
    assert 'JsonValue(pending.report_body, "filled_volume") != "0"' in source
    assert 'IsSafeAsciiToken(JsonValue(json, "idempotency_key"), 8, 250)' in validation
    assert '"PENDING_REPORT_INTEGRITY_INVALID"' in source
    assert "ConstantTimeBytesEqual(stored_integrity, expected_integrity)" in source
    assert "LoadPendingReport(pending, pending_error)" in on_init
    assert "return INIT_FAILED;" in on_init
    recovery = on_timer.index("RecoverPendingReport();")
    pending_return = on_timer.index("if(g_recovery_blocked || PendingReportExists())")
    poll = on_timer.index("PollOneCommand();")
    assert recovery < pending_return < poll


def test_pending_file_does_not_persist_long_lived_executor_secrets() -> None:
    source = _source()
    save = _between_functions(source, "SavePendingReport", "LoadPendingReport")

    assert "InpExecutorToken" not in save
    assert "InpCommandVerificationKey" not in save
    assert "FILE_COMMON" not in save


def test_http_diagnostics_log_only_bounded_metadata() -> None:
    source = _source()
    safe = _between_functions(source, "SafeLogValue", "ResponseHeaderValue")
    http = _between_functions(source, "HttpRequest", "AppendLedger")

    assert "character < 32" in safe
    assert "character == 0x2028" in safe
    assert "character >= 0x202A && character <= 0x202E" in safe
    assert "character >= 0x2066 && character <= 0x2069" in safe
    assert "StringLen(value) > max_length" in safe
    assert "response_sha256=%s" in http
    assert "response_bytes=%d" in http
    assert "looks_like_html=%s" in http
    assert "looks_like_json=%s" in http
    assert 'ResponseHeaderValue(response_headers, "Content-Type")' in http
    assert 'ResponseHeaderValue(response_headers, "X-Request-Id")' in http
    assert "response=%s" not in source
    assert "response_headers=%s" not in source
    assert 'PrintFormat("%s", InpExecutorToken)' not in source
    assert 'PrintFormat("%s", claim_token)' not in source


def test_http_diagnostics_correlate_requests_and_leave_success_path_quiet() -> None:
    http = _between_functions(_source(), "HttpRequest", "AppendLedger")

    request_id = http.index("string request_id = MakeUuid();")
    request_header = http.index('"X-Request-Id: " + request_id')
    request_log = http.index('"cf_ray=%s response_request_id=%s request_id=%s"')
    healthy_return = http.index('if(outcome == "HTTP_RESPONSE" && (code == 200 || code == 201 || code == 204))')
    response_classification = http.index("ClassifyResponseShape(")

    assert request_id < request_header < request_log
    assert healthy_return < response_classification
    assert '"Authorization: Bearer " + InpExecutorToken' in http
    assert "InpExecutorToken" not in http[http.index("if(code < 0)") :]
