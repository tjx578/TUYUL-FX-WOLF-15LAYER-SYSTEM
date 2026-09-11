"""Containment checks for the runtime credential pipe.

These are source-contract checks: they pin the shape of the MQL5 loader, the C#
broker and the JSON contract. They deliberately do not prove the transport works
-- that is what the PowerShell acceptance harness does, by compiling the helper,
performing a real DPAPI round-trip and reading a real named-pipe frame. Its
results and its full source are recorded in
``docs/convergence/d0-20260911/P3_CREDENTIAL_PIPE.md``. Keep both: source grep
alone never demonstrated a live pipe.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
DEMO = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Demo.mq5"
HELPER = ROOT / "tools" / "windows" / "wolf15_credential_broker" / "Wolf15CredentialBroker.cs"
EVIDENCE = ROOT / "docs" / "convergence" / "d0-20260911" / "P3_CREDENTIAL_PIPE.md"
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


def test_contract_binds_to_the_running_user_not_a_hardcoded_username() -> None:
    """The artifact must be portable across workstations.

    DPAPI CurrentUser plus a pipe ACL restricted to the running SID is the real
    boundary; a literal username in canonical source adds none and pins the
    build to one machine.
    """
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["server_identity"] == "CURRENT_WINDOWS_USER"
    assert contract["server_identity_binding"] == "RUNTIME_SID"
    assert contract["optional_expected_user_sid_argument"] is True
    assert "INTEL" not in json.dumps(contract)


def test_contract_does_not_claim_account_identity_authority() -> None:
    """account_reference_sha256 is an unkeyed digest of a low-entropy reference.

    It binds the envelope locally. It is not, and must never be presented as,
    broker/database account identity -- Channel B w15ab:v1 remains the authority
    and blocker B-B16 stays open regardless of this pipe.
    """
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["account_reference_sha256_authority"] == "LOCAL_CREDENTIAL_BINDING_ONLY"
    assert contract["account_identity_authority"] == "CHANNEL_B_W15AB_V1"


def test_contract_does_not_overclaim_secret_zeroization() -> None:
    """Byte buffers are cleared; .NET and MQL5 strings cannot be guaranteed."""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["secret_zeroization"] == "BEST_EFFORT_BYTE_BUFFERS_ONLY"


def test_ea_uses_a_pipe_path_input_and_no_direct_secret_inputs() -> None:
    source = _source(EA)
    # Named for what it is: a Windows local named-pipe endpoint, never a file
    # a credential could be parked in.
    assert "input string InpCredentialPipePath" in source
    assert "InpCredentialFile" not in source
    assert "input string InpExpectedAccountReferenceSha256" in source
    assert "InpExecutorToken" not in source
    assert "input string InpCommandVerificationKey " not in source
    assert "#import" not in source
    assert "StringFind(InpCredentialPipePath" in source
    assert 'reason = "CREDENTIAL_PIPE_UNAVAILABLE"' in source


def test_loader_rejects_malformed_truncated_oversize_trailing_and_extra_fields() -> None:
    loader = _function(_source(EA), "LoadRuntimeCredentials")
    assert "W15_CREDENTIAL_MAX_BYTES" in loader
    assert "header_read != W15_CREDENTIAL_HEADER_BYTES" in loader
    assert "payload_read != (uint)payload_length" in loader
    assert "trailing_read != 0" in loader
    # Re-serialising and comparing rejects missing, reordered, duplicated and
    # unknown fields in one step.
    assert "canonical != payload_json" in loader
    for reason in (
        "CREDENTIAL_SCHEMA_INVALID",
        "CREDENTIAL_PAYLOAD_OVERSIZE",
        "CREDENTIAL_PAYLOAD_TRUNCATED",
        "CREDENTIAL_TRAILING_BYTES",
    ):
        assert f'reason = "{reason}"' in loader


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
    for reason in ("EXECUTOR_BINDING_MISMATCH", "ACCOUNT_BINDING_MISMATCH", "KEY_ID_MISMATCH"):
        assert f'reason = "{reason}"' in loader
    assert "g_executor_token = executor_token" in loader
    assert "g_command_verification_key = verification_material" in loader


def test_credential_shapes_are_exact_lowercase_hex() -> None:
    """The backend derives the token as hmac-sha256 hexdigest: 64 lowercase hex.

    Length alone would accept uppercase or non-hex characters, so both secrets
    get an explicit alphabet contract.
    """
    source = _source(EA)
    loader = _function(source, "LoadRuntimeCredentials")
    assert "IsLowerHexExact(executor_token, 64)" in loader
    assert 'reason = "EXECUTOR_TOKEN_SHAPE_INVALID"' in loader
    assert 'TaggedHexToBytes(verification_material, "hex:", 32, verification_key)' in loader
    assert 'reason = "VERIFICATION_MATERIAL_SHAPE_INVALID"' in loader

    helper = _function(source, "IsLowerHexExact")
    assert "StringLen(value) != exact_length" in helper
    assert "character >= '0' && character <= '9'" in helper
    assert "character >= 'a' && character <= 'f'" in helper
    # No uppercase branch: uppercase hex must be rejected, not normalised.
    assert "'A'" not in helper and "'F'" not in helper


def test_both_active_on_init_handlers_recheck_runtime_credential_shape() -> None:
    for path in (EA, DEMO):
        source = _source(path)
        on_init = source[source.index("int OnInit()") : source.index("void OnTimer()")]
        assert "LoadRuntimeCredentials(credential_reason)" in on_init
        assert "IsLowerHexExact(g_executor_token, 64)" in on_init
        assert "IsSafeWireIdentifier(g_command_verification_key_id)" in on_init
        assert 'TaggedHexToBytes(g_command_verification_key, "hex:", 32, verification_key)' in on_init
        assert "ClearRuntimeCredentials();" in on_init


def test_runtime_secrets_replace_input_secrets_at_all_sinks() -> None:
    source = _source(EA)
    demo = _source(DEMO)
    assert '"Authorization: Bearer " + g_executor_token' in source
    assert "TaggedHexToBytes(g_command_verification_key" in source
    assert "key_id != g_command_verification_key_id" in source
    assert "TaggedHexToBytes(g_command_verification_key" in demo
    for path_source in (source, demo):
        deinit = path_source[path_source.index("void OnDeinit(") :]
        assert "ClearRuntimeCredentials();" in deinit


def test_logs_contain_reason_codes_but_never_secret_values() -> None:
    source = _source(EA)
    demo = _source(DEMO)
    loader = _function(source, "LoadRuntimeCredentials")
    assert "PrintFormat" not in loader
    for path_source in (source, demo):
        assert 'PrintFormat("%s", g_executor_token)' not in path_source
        assert 'PrintFormat("%s", g_command_verification_key)' not in path_source
        assert not re.search(r"Print(?:Format)?\([^\n]*(executor_token|verification_material)", path_source)


def test_helper_binds_to_the_running_sid_and_has_no_network_surface() -> None:
    helper = _source(HELPER)
    # Repaired: no hardcoded workstation account anywhere in canonical source.
    assert "INTEL" not in helper
    assert "ResolveCurrentUserSid" in helper
    assert "WindowsIdentity.GetCurrent()" in helper
    assert "expected-user-sid" in helper
    assert 'Fail("WRONG_WINDOWS_USER")' in helper

    assert "DataProtectionScope.CurrentUser" in helper
    assert "new NamedPipeServerStream(" in helper
    assert "PipeDirection.Out" in helper
    assert "BeginWaitForConnection" in helper
    assert "WaitOne(timeoutMs)" in helper
    assert "security.SetAccessRuleProtection(true, false)" in helper
    assert "new PipeAccessRule(sid, PipeAccessRights.ReadWrite, AccessControlType.Allow)" in helper

    assert "TcpClient" not in helper
    assert "HttpClient" not in helper
    assert "WebRequest" not in helper
    assert "File.WriteAll" not in helper
    assert "Console.WriteLine(" not in helper


def test_functional_evidence_is_recorded_for_the_live_path() -> None:
    """Source greps cannot show the pipe works, so the live proof is recorded.

    The PowerShell harness that produced these results is reproduced verbatim in
    the evidence document rather than stored as a .ps1 in the tree: on the build
    host, security software holds an exclusive handle on that specific script
    content, which made the file unreadable to git. See the document for the
    exact reproduction steps and the helper source digest the run was bound to.
    """
    evidence = _source(EVIDENCE)
    for gate in ("C16", "C17", "C18a", "C18b", "C18c", "C12", "C13", "C19", "C20"):
        assert f"| {gate} " in evidence
    assert "TOTAL=16 FAILED=0" in evidence
    assert "ProtectedData]::Protect" in evidence
    assert "NamedPipeClientStream" in evidence
    assert "GetAccessControl()" in evidence


def test_repair_does_not_change_order_entrypoints_or_arm_gate() -> None:
    demo = _source(DEMO)
    shadow = _source(EA)
    assert demo.count("OrderCheck(") == 1
    assert demo.count("OrderSend(") == 1
    assert shadow.count("OrderSend(") == 0
    assert shadow.count("OrderCheck(") == 0
    assert "if(!InpDemoExecutionArmed || InpLegacyShadowExecutionDisabled" in demo
    assert "ACCOUNT_TRADE_MODE_DEMO" in demo


def test_credential_port_preserves_the_monotonic_scheduler() -> None:
    """P2 must survive P3 untouched."""
    for path in (DEMO, EA):
        source = _source(path)
        timer = source[source.index("void OnTimer()") : source.index("void OnTick()")]
        assert "const ulong now_ms = GetTickCount64();" in timer
        assert "TimeCurrent(" not in timer
    assert "HistorySelect(issued - 300, TimeTradeServer() + 60)" in _source(DEMO)
