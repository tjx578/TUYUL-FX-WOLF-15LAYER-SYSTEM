import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_candidate_revision_v31 import (
    CandidateRevisionAppendV31,
    StoredCandidateRevisionV31,
    candidate_revision_hash_v31,
    prepare_candidate_revision_v31,
)
from storage.strategy_5scr_activity_consumer import LifecycleOwnerFence
from storage.strategy_5scr_candidate_revision_v31 import CandidateRevisionRepositoryV31, _stored
from tests.test_strategy_5scr_candidate_handoff_v31 import NOW, bundle


def revision(number=1, previous=None, advisory=False):
    _, handoff, _ = bundle()
    candidate = handoff.candidate.model_copy(
        update={
            "tradeplan_revision": number,
            "decision_at": NOW + timedelta(seconds=number - 1),
            "strategy_analysis_admission_id": UUID(int=100 + number),
        }
    )
    if advisory:
        candidate = candidate.model_copy(
            update={
                "analysis_admission_class": "MATURE_ADVISORY",
                "promotion_eligibility": "SHADOW_ONLY",
                "risk_handoff_allowed": False,
                "strategy_next_required_stage": "SHADOW_TERMINAL_REVIEW",
            }
        )
    handoff = handoff.model_copy(
        update={
            "candidate": candidate,
            "handoff_receipt_valid_until": NOW + timedelta(seconds=number + 1),
            "admission_receipt_hash": "sha256:" + f"{number:064x}",
        }
    )
    return CandidateRevisionAppendV31(
        profile="TEST_ONLY",
        revision_policy_id="APPEND_REEVALUATED_CANDIDATE_TEST_V1",
        handoff=handoff,
        predecessor_hash=previous.request_hash if previous else None,
        reevaluation_id=UUID(int=200 + number),
        reevaluation_receipt_hash="sha256:" + f"{number + 10:064x}",
    )


def prepared(request, previous=None, **overrides):
    kwargs = {
        "now": request.handoff.candidate.decision_at,
        "verify_reevaluation": lambda body, digest: digest == candidate_revision_hash_v31(request),
    }
    kwargs.update(overrides)
    return prepare_candidate_revision_v31(request, previous, **kwargs)


def test_advisory_to_canonical_appends_new_reevaluated_revision_without_mutation():
    first = prepared(revision(advisory=True))
    second = prepared(revision(2, first), first)
    assert first.request.handoff.candidate.risk_handoff_allowed is False
    assert second.request.handoff.candidate.tradeplan_revision == 2
    assert second.request.predecessor_hash == first.request_hash
    assert second.request.handoff.candidate.valid_for_execution is False
    assert StoredCandidateRevisionV31.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("revision", "PREDECESSOR_CONFLICT"),
        ("predecessor", "PREDECESSOR_CONFLICT"),
        ("symbol", "PLAN_SCOPE_CHANGED"),
        ("tradeplan_id", "PLAN_SCOPE_CHANGED"),
        ("strategy_lifecycle_id", "PLAN_SCOPE_CHANGED"),
        ("strategy_thesis_id", "PLAN_SCOPE_CHANGED"),
        ("clock", "FRESH_REEVALUATION_REQUIRED"),
        ("evaluation_id", "FRESH_REEVALUATION_REQUIRED"),
        ("evaluation_receipt", "FRESH_REEVALUATION_REQUIRED"),
        ("admission_id", "CANONICAL_ADMISSION_REBIND_REQUIRED"),
        ("admission_receipt", "CANONICAL_ADMISSION_REBIND_REQUIRED"),
    ],
)
def test_revision_cannot_relabel_stale_or_unrelated_evidence(fault, reason):
    first = prepared(revision(advisory=True))
    request = revision(2, first)
    candidate = request.handoff.candidate
    if fault == "revision":
        candidate = candidate.model_copy(update={"tradeplan_revision": 3})
    elif fault == "predecessor":
        request = request.model_copy(update={"predecessor_hash": "sha256:" + "f" * 64})
    elif fault in ("tradeplan_id", "strategy_lifecycle_id", "strategy_thesis_id"):
        candidate = candidate.model_copy(update={fault: UUID(int=999)})
    elif fault == "symbol":
        candidate = candidate.model_copy(update={"symbol": "XAUUSD"})
    elif fault == "clock":
        candidate = candidate.model_copy(update={"decision_at": NOW})
    elif fault == "evaluation_id":
        request = request.model_copy(update={"reevaluation_id": first.request.reevaluation_id})
    elif fault == "evaluation_receipt":
        request = request.model_copy(update={"reevaluation_receipt_hash": first.request.reevaluation_receipt_hash})
    elif fault == "admission_id":
        candidate = candidate.model_copy(
            update={"strategy_analysis_admission_id": first.request.handoff.candidate.strategy_analysis_admission_id}
        )
    elif fault == "admission_receipt":
        request = request.model_copy(
            update={
                "handoff": request.handoff.model_copy(
                    update={"admission_receipt_hash": first.request.handoff.admission_receipt_hash}
                )
            }
        )
    request = request.model_copy(update={"handoff": request.handoff.model_copy(update={"candidate": candidate})})
    with pytest.raises(ValueError, match=reason):
        prepared(request, first)


@pytest.mark.parametrize("offset", [-1, 2])
def test_new_revision_rejects_future_or_expired_receipt(offset):
    with pytest.raises(ValueError, match="RECEIPT_EXPIRED"):
        prepared(revision(), now=NOW + timedelta(seconds=offset))


@pytest.mark.parametrize("verifier", [None, lambda *_: False, lambda *_: 1])
def test_new_revision_requires_literal_verified_reevaluation(verifier):
    with pytest.raises(ValueError, match="VERIFICATION_REJECTED"):
        prepared(revision(), verify_reevaluation=verifier)


def test_verifier_mutation_is_rejected():
    def mutate(body, digest):
        object.__setattr__(body, "reevaluation_id", UUID(int=777))
        return True

    with pytest.raises(ValueError, match="REEVALUATION_CHANGED"):
        prepared(revision(), verify_reevaluation=mutate)


def test_hash_tampered_stored_history_rejected():
    stored = prepared(revision())
    with pytest.raises(ValidationError, match="STORED_HASH_MISMATCH"):
        StoredCandidateRevisionV31.model_validate({**stored.model_dump(), "request_hash": "sha256:" + "f" * 64})


def row_for(request):
    candidate = request.handoff.candidate
    return dict(
        tradeplan_id=candidate.tradeplan_id,
        revision=candidate.tradeplan_revision,
        symbol=candidate.symbol,
        reevaluation_id=request.reevaluation_id,
        predecessor_hash=request.predecessor_hash,
        request_hash=candidate_revision_hash_v31(request),
        request_payload=request.model_dump_json(),
    )


@pytest.mark.parametrize("field,value", [("revision", 9), ("symbol", "XAUUSD"), ("reevaluation_id", UUID(int=777))])
def test_row_and_payload_identity_must_agree(field, value):
    with pytest.raises(ValueError, match="ROW_IDENTITY_MISMATCH"):
        _stored({**row_for(revision()), field: value})


class FakeDB:
    """Protocol/fault fake only; no PostgreSQL concurrency or durability claim."""

    def __init__(self):
        self.rows = []
        self.active = False
        self.fail_commit = False
        self.commits = 0
        self.fence = LifecycleOwnerFence("EURUSD", "sha256:" + "a" * 64, "fixture", 1, UUID(int=55))

    def is_in_transaction(self):
        return self.active

    @asynccontextmanager
    async def transaction(self):
        old = list(self.rows)
        self.active = True
        try:
            yield self
            if self.fail_commit:
                raise RuntimeError("injected commit failure")
            self.commits += 1
        except BaseException:
            self.rows = old
            raise
        finally:
            self.active = False

    async def fetchrow(self, sql, *args):
        if "owner_fences" in sql:
            return vars(self.fence)
        rows = [r for r in self.rows if r["tradeplan_id"] == args[0]]
        if "ORDER BY" in sql:
            return max(rows, key=lambda r: r["revision"]) if rows else None
        return next((r for r in rows if r["revision"] == args[1]), None)

    async def execute(self, sql, *args):
        if "INSERT INTO public.strategy_5scr_candidate_revisions" in sql:
            self.rows.append(
                dict(
                    zip(
                        (
                            "tradeplan_id",
                            "revision",
                            "symbol",
                            "reevaluation_id",
                            "predecessor_revision",
                            "predecessor_hash",
                            "request_hash",
                            "request_payload",
                        ),
                        args,
                        strict=True,
                    )
                )
            )


def repository(db):
    return CandidateRevisionRepositoryV31(pg=db, fence=db.fence, verify_reevaluation=lambda *_: True)


def test_repository_commit_retry_and_latest_keep_immutable_history():
    async def run():
        db = FakeDB()
        repo = repository(db)
        request = revision(advisory=True)
        first = await repo.append(request, now=NOW)
        second_request = revision(2, first)
        second = await repo.append(second_request, now=NOW + timedelta(seconds=1))
        assert await repo.append(request, now=NOW + timedelta(days=1)) == first
        async with db.transaction():
            assert await repo.lock_latest(db, request.handoff.candidate.tradeplan_id) == second
        assert len(db.rows) == 2 and db.commits == 4
        conflict = request.model_copy(update={"reevaluation_receipt_hash": "sha256:" + "f" * 64})
        with pytest.raises(ValueError, match="PAYLOAD_CONFLICT"):
            await repo.append(conflict, now=NOW)

    asyncio.run(run())


def test_repository_does_not_ack_commit_failure():
    async def run():
        db = FakeDB()
        db.fail_commit = True
        with pytest.raises(RuntimeError, match="commit failure"):
            await repository(db).append(revision(), now=NOW)
        assert not db.rows and db.commits == 0

    asyncio.run(run())


def test_repository_caller_transaction_and_owner_are_required():
    async def run():
        db = FakeDB()
        repo = repository(db)
        with pytest.raises(ValueError, match="CALLER_TRANSACTION_REQUIRED"):
            await repo.append_in_transaction(db, revision(), now=NOW)
        db.fence = LifecycleOwnerFence("EURUSD", "sha256:" + "a" * 64, "next", 2, UUID(int=56))
        with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
            await repo.append(revision(), now=NOW)
        assert not db.rows

    asyncio.run(run())
