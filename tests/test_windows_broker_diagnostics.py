"""Execute only the CI-built broker, with synthetic failure fixtures, on Windows.

No compilation, real vault, MT5 connection, or trading endpoint is used here.
An unset executable skips local runs; a configured but missing EXE fails CI.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

EXE = os.environ.get("WOLF15_BROKER_TEST_EXE")
pytestmark = pytest.mark.skipif(os.name != "nt" or not EXE, reason="Requires explicitly selected Windows CI artifact")
SENTINEL = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_LOG"


def command(vault: Path, digest: str, pipe: str, mode: str) -> list[str]:
    return [
        str(Path(EXE).resolve()),
        "--vault",
        str(vault),
        "--vault-sha256",
        digest,
        "--pipe-name",
        pipe,
        "--executor-id",
        SENTINEL,
        "--account-reference",
        SENTINEL,
        "--broker-server",
        SENTINEL,
        "--verification-key-id",
        SENTINEL,
        "--account-reference-sha256",
        "0" * 64,
        "--timeout-ms",
        "1000",
        "--serve-mode",
        mode,
    ]


def assert_failure(result, code: int, reason: str, stage: str, category: str):
    assert result.returncode == code
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 2
    assert lines[0] == reason
    assert re.fullmatch(
        rf"W15_BROKER_DIAGNOSTIC_V1 stage={stage} exception={category} hresult=0x[0-9A-F]{{8}}",
        lines[1],
    )
    assert SENTINEL not in result.stderr


def test_argument_failure_preserves_exit_code_and_reason():
    result = subprocess.run([str(Path(EXE).resolve()), SENTINEL], capture_output=True, text=True, timeout=10)
    assert_failure(result, 2, "ARGUMENT_CONTRACT_INVALID", "Arguments", "ControlledFailure")


def test_missing_vault_does_not_disclose_path(tmp_path):
    result = subprocess.run(
        command(tmp_path / SENTINEL, "0" * 64, "wolf15-lean-d0-diagnostics", "once"),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert_failure(result, 2, "CREDENTIAL_VAULT_UNAVAILABLE", "VaultRead", "ControlledFailure")
    assert str(tmp_path) not in result.stderr


@pytest.mark.parametrize("mode", ["once", "persistent"])
def test_decrypt_failure_is_distinguishable_without_payload_disclosure(tmp_path, mode):
    data = SENTINEL.encode("ascii")
    vault = tmp_path / SENTINEL
    vault.write_bytes(data)  # Deliberately invalid DPAPI ciphertext, never a real vault.
    pipe = "wolf15-lean-d0-diagnostics-" + uuid.uuid4().hex
    args = command(vault, hashlib.sha256(data).hexdigest(), pipe, mode)
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        try:
            if mode == "persistent":
                # Persistent mode decrypts only after accepting a local client.
                deadline = time.monotonic() + 8
                while True:
                    try:
                        with open("\\\\.\\pipe\\" + pipe, "rb", buffering=0):
                            pass
                        break
                    except FileNotFoundError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise AssertionError("Synthetic pipe was not available") from None
                        time.sleep(0.05)
            stdout, stderr = process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()  # Only this test-owned CI child, never the acceptance broker.
                process.communicate()
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    assert_failure(result, 3, "DPAPI_HELPER_REJECTED", "VaultDecrypt", "CryptographicException")
    assert str(vault) not in result.stderr
