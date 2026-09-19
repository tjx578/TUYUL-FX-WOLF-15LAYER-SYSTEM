"""Owner decision S1 (2026-09-20): the main-branch StrategyAnalysisAdmissionV1 is LEGACY_NONCONFORMANT.

It stays as is, runtime-disabled unless explicitly enabled for legacy replay, with no risk or execution authority,
and it is never adapted into the native V31 chain (native replacement: StrategyAnalysisAdmissionV31, S1B-1).
"""

from __future__ import annotations

from contracts.strategy_5scr_analysis_admission import StrategyAnalysisAdmissionV1
from services.pressure_outbox.analysis_admission_v1_worker import StrategyAnalysisAdmissionRuntimeConfig


def test_legacy_s1b_is_disabled_by_default_and_shadow_only():
    config = StrategyAnalysisAdmissionRuntimeConfig.from_env({})
    assert (config.enabled, config.activation_requested, config.shadow_only) == (False, False, True)


def test_legacy_s1b_can_never_hold_risk_or_execution_authority():
    fields = StrategyAnalysisAdmissionV1.model_fields
    for name in ("risk_authority", "execution_authority", "valid_for_execution"):
        assert fields[name].default is False
    assert fields["final_direction"].default == "WAIT"
