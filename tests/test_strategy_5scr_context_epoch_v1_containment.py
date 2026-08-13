"""Containment and runtime configuration gates for ContextEpoch P3."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from storage.strategy_5scr_context_epoch_v1_repository import ContextEpochV1RuntimeConfig

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_defaults_disabled_and_shadow_only() -> None:
    config = ContextEpochV1RuntimeConfig.from_env({})
    assert config.enabled is False
    assert config.shadow_only is True
    config.validate()


def test_enabled_non_shadow_configuration_fails_closed() -> None:
    config = ContextEpochV1RuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_CONTEXT_EPOCH_V1_WRITER_ENABLED": "true",
            "STRATEGY_5SCR_CONTEXT_EPOCH_V1_SHADOW_ONLY": "false",
        }
    )
    with pytest.raises(RuntimeError, match="SHADOW_ONLY_REQUIRED"):
        config.validate()


def test_context_epoch_has_only_audited_downstream_analysis_consumers() -> None:
    allowed = {
        "analysis/strategy_5scr_context_epoch_v1.py",
        "analysis/strategy_5scr_directional_thesis_v1.py",
        "analysis/strategy_5scr_tradeplan_candidate_v2.py",
        "contracts/strategy_5scr_context_epoch_v1.py",
        "storage/strategy_5scr_context_epoch_v1_repository.py",
        "storage/strategy_5scr_directional_thesis_v1_repository.py",
        "storage/migrations/versions/20260812_01_5scr_context_epoch_v1.py",
    }
    result = subprocess.run(
        (
            "git",
            "grep",
            "-l",
            "-e",
            "strategy_5scr_context_epoch_v1",
            "-e",
            "CONTEXT_EPOCH_V1_WRITER",
            "--",
            "*.py",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in {0, 1}, result.stderr
    consumers = [
        path.replace("\\", "/")
        for path in result.stdout.splitlines()
        if path.replace("\\", "/") not in allowed and not path.replace("\\", "/").startswith("tests/")
    ]
    assert consumers == []


def test_p3_files_do_not_import_downstream_authority() -> None:
    targets = (
        ROOT / "analysis" / "strategy_5scr_context_epoch_v1.py",
        ROOT / "contracts" / "strategy_5scr_context_epoch_v1.py",
        ROOT / "storage" / "strategy_5scr_context_epoch_v1_repository.py",
    )
    forbidden = (
        "directional_thesis",
        "execution_box",
        "tradeplan",
        "risk_reservation",
        "execution_command",
        "ordersend",
    )
    for target in targets:
        source = target.read_text(encoding="utf-8").lower()
        assert not any(item in source for item in forbidden), target
