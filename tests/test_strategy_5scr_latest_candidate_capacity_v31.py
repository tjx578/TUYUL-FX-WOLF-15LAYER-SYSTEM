import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_reference_pattern_v31 import ReferencePatternHandoffVerifierV31
from analysis.strategy_5scr_target_selection_v31 import target_universe_hash_v31
from contracts.strategy_5scr_candidate_revision_v31 import CandidateCapacityPreparationV31
from risk.strategy_5scr_candidate_handoff_v31 import candidate_handoff_hash_v31
from risk.strategy_5scr_risk_adapter_v31 import parent_sizing_request_hash_v31
from tests.test_strategy_5scr_candidate_handoff_v31 import bundle
from tests.test_strategy_5scr_candidate_revision_v31 import NOW, FakeDB, repository, revision
from tests.test_strategy_5scr_ordered_proof_v31 import reference_policy


async def fixture(advisory=False):
    db = FakeDB()
    repo = repository(db)
    append = revision(advisory=advisory)
    stored = await repo.append(append, now=NOW)
    ledger, _, request = bundle()
    handoff = stored.request.handoff
    request = request.model_copy(update={"strategy_candidate_receipt_hash": candidate_handoff_hash_v31(handoff)})
    kwargs = {
        "expected_candidate_revision_hash": stored.request_hash,
        "ledger": ledger,
        "request": request,
        "reservation_id": UUID(int=91),
        "expires_at": NOW + timedelta(seconds=1),
        "now": NOW,
        "capacity_owner_epoch": ledger.owner_epoch,
        "expected_capacity_version": ledger.version,
        "verify_handoff": ReferencePatternHandoffVerifierV31(
            policy=reference_policy(), attest_remaining=lambda _, digest: digest == candidate_handoff_hash_v31(handoff)
        ),
        "verify_universe": lambda _, digest: digest == target_universe_hash_v31(handoff.target_universe),
        "verify_risk_inputs": lambda _, digest: digest == parent_sizing_request_hash_v31(request),
    }
    return db, repo, stored, kwargs


def test_caller_loads_locked_current_candidate_then_runs_actual_capacity_handoff():
    async def run():
        db, repo, stored, kwargs = await fixture()
        async with db.transaction():
            result = await repo.prepare_parent_in_transaction(db, **kwargs)
            assert result.candidate_revision == stored
            assert result.capacity.ledger.version == 1
            assert result.capacity.reservation.strategy_candidate_receipt_hash == candidate_handoff_hash_v31(
                stored.request.handoff
            )
            assert result.durable_commit is result.capital_reservation_authority is result.execution_authority is False
        assert kwargs["ledger"].reservations == ()
        assert len(db.rows) == 1  # Preparation does not claim to persist risk/outbox effects.

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("missing", "LATEST_REVISION_UNAVAILABLE"),
        ("hash", "LATEST_REVISION_MISMATCH"),
        ("revision", "LATEST_REVISION_MISMATCH"),
        ("handoff", "HANDOFF_RECEIPT_MISMATCH"),
        ("capacity_epoch", "OWNER_FENCED"),
        ("capacity_version", "VERSION_CONFLICT"),
        ("expiry", "RECEIPT_EXPIRED"),
        ("transaction", "CALLER_TRANSACTION_REQUIRED"),
    ],
)
def test_latest_candidate_capacity_denies_missing_or_conflicting_binding(fault, reason):
    async def run():
        db, repo, _, kwargs = await fixture()
        if fault == "missing":
            db.rows = []
        elif fault == "hash":
            kwargs["expected_candidate_revision_hash"] = "sha256:" + "f" * 64
        elif fault == "revision":
            kwargs["request"] = kwargs["request"].model_copy(update={"tradeplan_revision": 2})
        elif fault == "handoff":
            kwargs["request"] = kwargs["request"].model_copy(
                update={"strategy_candidate_receipt_hash": "sha256:" + "f" * 64}
            )
        elif fault == "capacity_epoch":
            kwargs["capacity_owner_epoch"] += 1
        elif fault == "capacity_version":
            kwargs["expected_capacity_version"] += 1
        elif fault == "expiry":
            kwargs["now"] = NOW + timedelta(seconds=2)
        with pytest.raises(ValueError, match=reason):
            if fault == "transaction":
                await repo.prepare_parent_in_transaction(db, **kwargs)
            else:
                async with db.transaction():
                    await repo.prepare_parent_in_transaction(db, **kwargs)

    asyncio.run(run())


def test_superseded_revision_cannot_enter_capacity_even_with_matching_old_receipt():
    async def run():
        db, repo, first, kwargs = await fixture()
        second = await repo.append(revision(2, first), now=NOW + timedelta(seconds=1))
        for expected in (first.request_hash, second.request_hash):
            kwargs["expected_candidate_revision_hash"] = expected
            with pytest.raises(ValueError, match="LATEST_REVISION_MISMATCH"):
                async with db.transaction():
                    await repo.prepare_parent_in_transaction(db, **kwargs)
        assert await repo.append(first.request, now=NOW + timedelta(days=1)) == first

    asyncio.run(run())


def test_advisory_history_cannot_gain_risk_authority_through_storage():
    async def run():
        db, repo, _, kwargs = await fixture(advisory=True)

        def forbidden(*_):
            raise AssertionError("advisory reached verifier")

        kwargs.update(verify_handoff=forbidden, verify_universe=forbidden, verify_risk_inputs=forbidden)
        with pytest.raises(ValueError, match="ADVISORY_RISK_HANDOFF_PROHIBITED"):
            async with db.transaction():
                await repo.prepare_parent_in_transaction(db, **kwargs)

    asyncio.run(run())


def test_preparation_contract_cannot_claim_commit_or_substitute_candidate_identity():
    async def run():
        db, repo, _, kwargs = await fixture()
        async with db.transaction():
            result = await repo.prepare_parent_in_transaction(db, **kwargs)
        with pytest.raises(ValidationError):
            CandidateCapacityPreparationV31.model_validate({**result.model_dump(), "durable_commit": True})
        payload = result.model_dump()
        payload["candidate_revision"]["request"]["handoff"]["candidate"]["tradeplan_revision"] = 2
        with pytest.raises(ValidationError):
            CandidateCapacityPreparationV31.model_validate(payload)

    asyncio.run(run())
