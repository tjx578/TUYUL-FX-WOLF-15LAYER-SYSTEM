from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
DEMO = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Demo.mq5"
HELPER = ROOT / "tools" / "windows" / "wolf15_credential_broker" / "Wolf15CredentialBroker.cs"
CONTRACT = ROOT / "ea_interface" / "wolf15_executor" / "credential-pipe-contract.v1.json"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    start = source.index(f"{name}(")
    next_marker = source.find("//+------------------------------------------------------------------+", start)
    assert next_marker > start
    return source[start:next_marker]


def test_contract_is_one_shot_local_and_bounded() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["transport"] == "WINDOWS_LOCAL_NAMED_PIPE"
    assert contract["maximum_server_instances"] == 1
    assert contract["serve_count"] == 1
    assert contract["frame"]["maximum_payload_bytes"] == 4096
    assert contract["credential_fields"] == ["executor_token", "verification_material"]
    assert contract["network_access"] is False
    assert contract["plaintext_files"] is False
    assert contract["console_secret_output"] is False
    assert contract["dll_import_required_by_mq5"] is False


def test_ea_uses_pipe_reference_and_no_direct_secret_inputs() -> None:
    source = _source(EA)
    assert 'input string InpCredentialFile' in source
    assert 'input string InpExpectedAccountReferenceSha256' in source
    assert 'input string InpExecutorToken' not in source
    assert 'input string InpCommandVerificationKey   =' not in source
    assert "#import" not in source
    assert "StringFind(InpCredentialFile" in source
    assert 'reason = "CREDENTIAL_PIPE_UNAVAILABLE"' in source


def test_loader_rejects_malformed_truncated_oversize_and_extra_fields() -> None:
    loader = _function(_source(EA), "LoadRuntimeCredentials")
    assert "W15_CREDENTIAL_MAX_BYTES" in loader
    assert "header_read != W15_CREDENTIAL_HEADER_BYTES" in loader
    assert "payload_read != payload_length" in loader
    assert "trailing_read != 0" in loader
    assert "canonical != payload_json" in loader
    assert 'reason = "CREDENTIAL_SCHEMA_INVALID"' in loader
    assert 'reason = "CREDENTIAL_PAYLOAD_OVERSIZE"' in loader


def test_loader_checks_all_nonsecret_bindings_and_exact_two_credentials() -> None:
    source = _source(EA)
    loader = _function(source, "LoadRuntimeCredentials")
    assert '#define W15_CREDENTIAL_SCHEMA "wolf15.runtime_credentials.v1"' in source
    for field in (
        "W15_CREDENTIAL_SCHEMA",
        "InpExecutorId",
        "InpExpectedAccountReferenceSha256",
        "InpCommandVerificationKeyId",
        "executor_token",
        "verification_material",
    ):
        assert field in loader
    assert "g_executor_token = executor_token" in loader
    assert "g_command_verification_key = verification_material" in loader


def test_runtime_secrets_replace_input_secrets_at_all_sinks() -> None:
    source = _source(EA)
    demo = _source(DEMO)
    assert '"Authorization: Bearer " + g_executor_token' in source
    assert "TaggedHexToBytes(g_command_verification_key" in source
    assert "key_id != g_command_verification_key_id" in source
    assert "TaggedHexToBytes(g_command_verification_key" in demo
    assert "ClearRuntimeCredentials();" in source
    assert "ClearRuntimeCredentials();" in demo


def test_logs_contain_reason_codes_but_never_secret_values() -> None:
    source = _source(EA)
    loader = _function(source, "LoadRuntimeCredentials")
    assert "PrintFormat" not in loader
    assert 'PrintFormat("%s", g_executor_token)' not in source
    assert 'PrintFormat("%s", g_command_verification_key)' not in source
    assert not re.search(r"Print(?:Format)?\([^\n]*(executor_token|verification_material)", source)


def test_helper_is_current_user_one_shot_and_has_no_network_surface() -> None:
    helper = _source(HELPER)
    assert 'EndsWith("\\\\INTEL"' in helper
    assert "DataProtectionScope.CurrentUser" in helper
    assert "new NamedPipeServerStream(" in helper
    assert "PipeDirection.Out" in helper
    assert "\n            1,\n            PipeTransmissionMode.Byte" in helper
    assert "BeginWaitForConnection" in helper
    assert "WaitOne(timeoutMs)" in helper
    assert "TcpClient" not in helper
    assert "HttpClient" not in helper
    assert "WebRequest" not in helper
    assert "File.WriteAll" not in helper
    assert "Console.WriteLine(" not in helper


def test_repair_does_not_change_order_entrypoints_or_arm_gate() -> None:
    demo = _source(DEMO)
    assert demo.count("OrderCheck(") == 1
    assert demo.count("OrderSend(") == 1
    assert "if(!InpDemoExecutionArmed || InpLegacyShadowExecutionDisabled" in demo
    assert "ACCOUNT_TRADE_MODE_DEMO" in demo
