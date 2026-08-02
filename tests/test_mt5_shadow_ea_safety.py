"""Static safety contract for the MT5 SHADOW executor source."""

from __future__ import annotations

import re
from pathlib import Path

EA_SOURCE = Path(__file__).resolve().parents[1] / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"


def _source() -> str:
    return EA_SOURCE.read_text(encoding="utf-8")


def _on_init(source: str) -> str:
    match = re.search(r"\bint\s+OnInit\s*\(\s*\)(.*?)\bvoid\s+OnTimer\s*\(", source, re.DOTALL)
    assert match is not None, "EA source must define OnInit before OnTimer"
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
    assert "executor_id_length=%d token_length=%d login_hash_length=%d" in on_init
    assert 'PrintFormat("%s", InpExecutorToken)' not in on_init
    assert 'PrintFormat("%s", InpLoginHash)' not in on_init
