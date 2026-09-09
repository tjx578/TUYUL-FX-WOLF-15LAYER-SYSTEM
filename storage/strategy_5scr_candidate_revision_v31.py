"""Explicitly injected PostgreSQL candidate history; no runtime activation.

Append acknowledgement leaves the owned transaction only after commit. The
in-transaction variant returns a tentative record for composition, not an ACK.
No default connection, owner acquisition, migration or risk effect is supplied.
"""

from contracts.strategy_5scr_candidate_revision_v31 import (
    CandidateRevisionAppendV31,
    StoredCandidateRevisionV31,
    candidate_revision_hash_v31,
    prepare_candidate_revision_v31,
)
from storage.strategy_5scr_activity_consumer import bind_owner

TABLE = "public.strategy_5scr_candidate_revisions_v31"


def _stored(row):
    if row is None:
        return None
    request = CandidateRevisionAppendV31.model_validate_json(row["request_payload"])
    candidate = request.handoff.candidate
    if (
        str(row["tradeplan_id"]) != str(candidate.tradeplan_id)
        or row["revision"] != candidate.tradeplan_revision
        or row["symbol"] != candidate.symbol
        or str(row["reevaluation_id"]) != str(request.reevaluation_id)
        or row["predecessor_hash"] != request.predecessor_hash
    ):
        raise ValueError("CANDIDATE_ROW_IDENTITY_MISMATCH")
    return StoredCandidateRevisionV31(request=request, request_hash=row["request_hash"])


class CandidateRevisionRepositoryV31:
    def __init__(self, *, pg, fence, verify_reevaluation):
        self._pg = pg
        self.fence = fence
        self._verify = verify_reevaluation

    async def _bind(self, connection):
        if not connection.is_in_transaction():
            raise ValueError("CANDIDATE_CALLER_TRANSACTION_REQUIRED")
        await bind_owner(connection, self.fence)

    async def lock_latest(self, connection, tradeplan_id):
        """Locked history fact only: caller must validate current risk authority."""
        await self._bind(connection)
        row = await connection.fetchrow(
            f"SELECT * FROM {TABLE} WHERE tradeplan_id=$1 ORDER BY revision DESC LIMIT 1 FOR UPDATE", tradeplan_id
        )
        stored = _stored(row)
        if stored and stored.request.handoff.candidate.symbol != self.fence.symbol:
            raise ValueError("CANDIDATE_OWNER_SYMBOL_MISMATCH")
        return stored

    async def append_in_transaction(self, connection, request: CandidateRevisionAppendV31, *, now):
        request = CandidateRevisionAppendV31.model_validate(request.model_dump())
        candidate = request.handoff.candidate
        if candidate.symbol != self.fence.symbol:
            raise ValueError("CANDIDATE_OWNER_SYMBOL_MISMATCH")
        latest = await self.lock_latest(connection, candidate.tradeplan_id)
        existing = _stored(
            await connection.fetchrow(
                f"SELECT * FROM {TABLE} WHERE tradeplan_id=$1 AND revision=$2",
                candidate.tradeplan_id,
                candidate.tradeplan_revision,
            )
        )
        if existing:
            if existing.request_hash != candidate_revision_hash_v31(request):
                raise ValueError("CANDIDATE_REVISION_PAYLOAD_CONFLICT")
            # Historical acknowledgement does not move latest backwards or renew expiry.
            return existing
        prepared = prepare_candidate_revision_v31(request, latest, now=now, verify_reevaluation=self._verify)
        await connection.execute(
            f"INSERT INTO {TABLE}(tradeplan_id,revision,symbol,reevaluation_id,predecessor_revision,"
            "predecessor_hash,request_hash,request_payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            candidate.tradeplan_id,
            candidate.tradeplan_revision,
            candidate.symbol,
            request.reevaluation_id,
            candidate.tradeplan_revision - 1 if candidate.tradeplan_revision > 1 else None,
            request.predecessor_hash,
            prepared.request_hash,
            request.model_dump_json(),
        )
        return prepared

    async def append(self, request: CandidateRevisionAppendV31, *, now):
        async with self._pg.transaction() as connection:
            result = await self.append_in_transaction(connection, request, now=now)
        return result
