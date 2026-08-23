"""Unit gates for command-inert C2 SHADOW risk projections."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_shadow_risk_projection import (
    ShadowRiskProjectionInputIntegrityError,
    Strategy5SCRShadowRiskProjectionEvaluatorV1,
)
from contracts.strategy_5scr_shadow_risk_projection import (
    C2_SHADOW_SOURCE_ADMISSION_CLASS,
    C2ShadowRiskProjectionDecision,
    C2ShadowRiskProjectionState,
    C2ShadowRiskProjectionV1,
)
from risk.s5_campaign_risk import CampaignRiskPolicy
from tests.test_strategy_5scr_candidate_c2_shadow_v2 import _evidence


def _would_reserve() -> tuple[object, C2ShadowRiskProjectionV1]:
    evidence = _evidence("BUY", kill_switch="ENGAGED")
    result = Strategy5SCRShadowRiskProjectionEvaluatorV1().evaluate(
        evidence,
        source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
    )
    assert result.projection is not None
    return evidence, result.projection


def test_engaged_kill_switch_produces_inert_would_reserve_projection() -> None:
    _, projection = _would_reserve()

    assert projection.decision is C2ShadowRiskProjectionDecision.WOULD_RESERVE
    assert projection.state is C2ShadowRiskProjectionState.AVAILABLE
    assert projection.reason_code == "C2_SHADOW_WOULD_RESERVE"
    assert projection.kill_switch_observed == "ENGAGED"
    assert projection.would_volume is not None
    assert projection.would_risk_usd is not None
    assert projection.would_open_risk_after_usd is not None
    assert projection.would_margin_status == "NOT_MEASURED"
    assert projection.would_margin_usd is None
    assert projection.execution_authority is False
    assert projection.capital_reserved is False
    assert projection.broker_side_effect_allowed is False
    assert projection.order_send_eligible is False


def test_mature_advisory_is_a_typed_rejection_without_projection() -> None:
    result = Strategy5SCRShadowRiskProjectionEvaluatorV1().evaluate(
        None,
        source_admission_class="MATURE_ADVISORY",
    )

    assert result.source_admission_class == "MATURE_ADVISORY"
    assert result.decision is C2ShadowRiskProjectionDecision.WOULD_REJECT
    assert result.reason_code == "C2_SHADOW_SOURCE_NOT_CANONICAL"
    assert result.projection is None


def test_canonical_admission_requires_real_candidate_evidence() -> None:
    with pytest.raises(ShadowRiskProjectionInputIntegrityError, match="canonical Candidate V2 evidence is required"):
        Strategy5SCRShadowRiskProjectionEvaluatorV1().evaluate(
            None,
            source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
        )


def test_disengaged_kill_switch_cannot_form_shadow_projection() -> None:
    with pytest.raises(ShadowRiskProjectionInputIntegrityError, match="kill switch ENGAGED"):
        Strategy5SCRShadowRiskProjectionEvaluatorV1().evaluate(
            _evidence("BUY", kill_switch="DISENGAGED"),
            source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
        )


def test_noncanonical_policy_is_durable_would_reject_without_sizing() -> None:
    policy = CampaignRiskPolicy(
        risk_percent_per_entry=Decimal("0.04"),
        max_total_open_risk_percent=Decimal("0.10"),
    )
    result = Strategy5SCRShadowRiskProjectionEvaluatorV1(policy).evaluate(
        _evidence("BUY", kill_switch="ENGAGED"),
        source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
    )

    assert result.decision is C2ShadowRiskProjectionDecision.WOULD_REJECT
    assert result.reason_code == "C2_SHADOW_RISK_POLICY_NOT_CANONICAL"
    assert result.projection is not None
    assert result.projection.state is C2ShadowRiskProjectionState.REJECTED
    assert result.projection.would_volume is None
    assert result.projection.would_risk_usd is None
    assert result.projection.would_open_risk_after_usd is None


@pytest.mark.parametrize(
    "field",
    [
        "execution_authority",
        "capital_reserved",
        "broker_side_effect_allowed",
        "order_send_eligible",
    ],
)
def test_projection_contract_rejects_any_execution_authority_flag(field: str) -> None:
    _, projection = _would_reserve()
    payload = projection.model_dump(mode="python")
    payload[field] = True

    with pytest.raises(ValidationError):
        C2ShadowRiskProjectionV1.model_validate(payload)


def test_projection_identity_is_deterministic_for_exact_evidence() -> None:
    evidence = _evidence("BUY", kill_switch="ENGAGED")
    evaluator = Strategy5SCRShadowRiskProjectionEvaluatorV1()

    first = evaluator.evaluate(evidence, source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS)
    second = evaluator.evaluate(evidence, source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS)

    assert first == second
    assert first.projection is not None and second.projection is not None
    assert first.projection.shadow_authority_id == second.projection.shadow_authority_id
    assert first.projection.authority_hash == second.projection.authority_hash
