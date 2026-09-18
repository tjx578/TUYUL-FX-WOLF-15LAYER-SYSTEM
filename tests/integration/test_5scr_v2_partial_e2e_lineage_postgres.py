"""Step 5F-A: one durable lineage through the modular V2 analysis chain, on disposable PostgreSQL.

lifecycle -> context_epoch_v1 -> H1/M15 proofs -> directional_thesis_v1 -> execution_box_v1
-> tradeplan_candidate_v2 -> candidate_c2_shadow_v2 (SHADOW authority bundle).

Every stage is persisted by its own repository; this test proves that the rows join into one
lineage and that the chain has zero broker effect. It is PARTIAL_E2E by construction: the
lifecycle/pressure link and the thesis direction are fixture inputs (no runtime driver calls
these repositories), and V2 does not hand off to capacity_v31/transaction_a_v31.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from tests.integration.test_5scr_candidate_c2_shadow_v2_postgres import (
    _P7_TABLES,
    _external_counts,
    _p7_counts,
    _repository,
    _seeded,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_LINEAGE_SQL = """
SELECT
    l.strategy_lifecycle_id AS lifecycle_id,
    e.context_epoch_id, e.strategy_lifecycle_id AS epoch_lifecycle_id, e.symbol AS epoch_symbol,
    t.strategy_thesis_id, t.context_epoch_id AS thesis_epoch_id, t.strategy_lifecycle_id AS thesis_lifecycle_id,
    t.strategy_direction AS thesis_direction, t.direction_immutable,
    t.valid_for_execution AS thesis_valid_for_execution, t.execution_authority AS thesis_execution_authority,
    h1.strategy_direction AS h1_direction, h1.context_epoch_id AS h1_epoch_id,
    m15.strategy_direction AS m15_direction, m15.h1_proof_id AS m15_h1_proof_id,
    b.execution_box_id, b.strategy_thesis_id AS box_thesis_id, b.strategy_direction AS box_direction,
    c.tradeplan_id, c.execution_box_id AS candidate_box_id, c.strategy_thesis_id AS candidate_thesis_id,
    c.context_epoch_id AS candidate_epoch_id, c.strategy_lifecycle_id AS candidate_lifecycle_id,
    c.strategy_direction AS candidate_direction,
    h.tradeplan_id AS handoff_tradeplan_id, h.execution_box_id AS handoff_box_id,
    h.strategy_thesis_id AS handoff_thesis_id, h.context_epoch_id AS handoff_epoch_id,
    h.strategy_lifecycle_id AS handoff_lifecycle_id, h.strategy_direction AS handoff_direction
FROM strategy_5scr_candidate_c2_handoffs_v2 h
JOIN strategy_5scr_tradeplan_candidates_v2 c ON c.tradeplan_id = h.tradeplan_id
JOIN strategy_5scr_execution_boxes_v1 b ON b.execution_box_id = c.execution_box_id
JOIN strategy_5scr_directional_theses_v1 t ON t.strategy_thesis_id = b.strategy_thesis_id
JOIN strategy_5scr_h1_structure_proofs_v1 h1 ON h1.h1_proof_id = t.h1_proof_id
JOIN strategy_5scr_m15_structural_proofs_v1 m15 ON m15.m15_proof_id = t.m15_proof_id
JOIN strategy_5scr_context_epochs_v1 e ON e.context_epoch_id = t.context_epoch_id
JOIN strategy_5scr_analysis_lifecycles_v2 l ON l.strategy_lifecycle_id = e.strategy_lifecycle_id
WHERE h.tradeplan_id = $1
"""


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
async def test_v2_analysis_chain_is_one_durable_lineage_without_broker_effect(
    postgres: PoolBackedPostgres,
    direction: Literal["BUY", "SELL"],
) -> None:
    async with _seeded(postgres, direction=direction) as seeded:
        before = await _external_counts(postgres, seeded)
        candidate = seeded.candidate
        result = await _repository(postgres).process_evidence(seeded.evidence)
        assert (result.status, result.reason_code) == ("APPROVED", "C2_SHADOW_RISK_AUTHORIZED")
        assert result.authority_bundle is not None

        rows = await postgres.fetch(_LINEAGE_SQL, candidate.tradeplan_id)
        assert len(rows) == 1, "ONE_LINEAGE: exactly one joined row from handoff back to lifecycle"
        row = dict(rows[0])

        # ONE_LINEAGE: every stage references the same parents, persisted by its own repository.
        assert row["lifecycle_id"] == seeded.lifecycle_id
        assert (
            row["epoch_lifecycle_id"]
            == row["thesis_lifecycle_id"]
            == row["candidate_lifecycle_id"]
            == row["handoff_lifecycle_id"]
            == seeded.lifecycle_id
        )
        assert row["thesis_epoch_id"] == row["h1_epoch_id"] == row["candidate_epoch_id"] == row["handoff_epoch_id"]
        assert row["thesis_epoch_id"] == row["context_epoch_id"] == candidate.context_epoch_id
        assert row["box_thesis_id"] == row["candidate_thesis_id"] == row["handoff_thesis_id"]
        assert row["strategy_thesis_id"] == candidate.strategy_thesis_id
        assert row["candidate_box_id"] == row["handoff_box_id"] == row["execution_box_id"] == candidate.execution_box_id
        assert row["m15_h1_proof_id"] is not None
        assert row["epoch_symbol"] == candidate.symbol

        # Direction is fixed at the thesis, bound to its H1/M15 proof rows, and never changes downstream.
        assert row["direction_immutable"] is True
        assert (
            row["h1_direction"]
            == row["m15_direction"]
            == row["thesis_direction"]
            == row["box_direction"]
            == row["candidate_direction"]
            == row["handoff_direction"]
            == direction
        )
        assert result.authority_bundle.handoff.direction == direction

        # Strategy stages carry no execution authority; P7 stays SHADOW with no broker/command authority.
        assert row["thesis_valid_for_execution"] is False and row["thesis_execution_authority"] is False
        assert candidate.valid_for_execution is False and candidate.execution_authority is False
        bundle = result.authority_bundle
        assert bundle.reservation.execution_mode == "SHADOW"
        assert bundle.reservation.broker_execution_authority is False
        assert bundle.reservation.command_authority is False
        assert bundle.final_signal.delivery_authority is False

        # BROKER_ECONOMICS_INPUT: the candidate carries the broker geometry it was solved against.
        assert candidate.broker_tick_size > 0 and candidate.broker_point > 0
        assert candidate.broker_authority_hash.startswith("sha256:")

        # DUPLICATE = 0 and BROKER_EFFECT = 0.
        assert await _p7_counts(postgres, candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}
        replay = await _repository(postgres).process_evidence(seeded.evidence)
        assert replay.status == "DUPLICATE"
        assert await _p7_counts(postgres, candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}
        after = await _external_counts(postgres, seeded)
        assert after == before
        assert (after["commands"], after["reports"], after["broker"]) == (0, 0, 0)
