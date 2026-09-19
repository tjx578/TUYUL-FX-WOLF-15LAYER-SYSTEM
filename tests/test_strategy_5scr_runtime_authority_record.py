"""The 5S-CR runtime authority record is single-authority, hash-exact and enables nothing at runtime."""

import hashlib
import json
from pathlib import Path
from typing import get_args

from contracts.strategy_5scr_activity_runtime import SELECTED_SSOT_SHA256
from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "governance" / "strategy-5scr-runtime-authority.json"


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_new_authority_is_the_exact_byte_bound_ssot_pinned_by_v31():
    new = _record()["new_runtime_authority"]
    digest = hashlib.sha256((ROOT / new["path"]).read_bytes()).hexdigest()
    assert digest == new["sha256"] == SELECTED_SSOT_SHA256
    assert get_args(CandidateHandoffV31.model_fields["selected_ssot_hash"].annotation) == (f"sha256:{digest}",)
    assert new["status"] == "APPROVED_RUNTIME_AUTHORITY" and new["document_bytes_modified"] is False


def test_exactly_one_authority_and_previous_is_superseded():
    record = _record()
    previous = record["previous_runtime_authority"]
    assert (ROOT / previous["path"]).is_file()
    assert previous["status"] == "SUPERSEDED_LEGACY"
    assert record["dual_authority"] is False
    assert record["runtime_family"]["authoritative"] == "V31"
    assert "V2" in record["runtime_family"]["legacy_non_authoritative"]
    assert record["runtime_family"]["v2_to_v31_adapter"].startswith("PROHIBITED")


def test_promotion_enables_nothing_at_runtime():
    record = _record()
    assert record["runtime_execution_enablement"] is False
    assert record["broker_effect"] == 0
    assert record["activation_event"] == "MERGE_OF_THIS_RECORD_INTO_MAIN"
    assert {"deploy", "execution", "enqueue", "arm", "order_submission", "algo_trading", "broker_effect"} <= set(
        record["promotion_does_not_enable"]
    )


def test_known_gaps_and_merge_prerequisites_are_declared():
    record = _record()
    gaps = {gap["id"] for gap in record["known_implementation_gaps"]}
    assert {"G1", "G1b", "V31_UPSTREAM_PRODUCER", "V31_ONE_LINEAGE_E2E", "LIVE_30_PAIR_READINESS"} <= gaps
    assert len(record["merge_prerequisites"]) >= 6
