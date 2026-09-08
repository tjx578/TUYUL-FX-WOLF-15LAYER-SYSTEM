"""Serialized PostgreSQL activity evaluation, attachment and recovery.

This store owns only versioned activity tables. It never reserves capital,
creates commands, runs migrations or obtains a DSN from the general database
environment. All scope and policy choices are explicit constructor inputs.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from analysis.strategy_5scr_pair_activity import (
    build_pair_activity_audit,
    normalize_pair_activity_observations,
    pair_activity_raw_event_id,
)
from contracts.strategy_5scr_activity_runtime import ActivityCoverageCheckpointV1, ActivityRuntimeBindingV1
from contracts.strategy_5scr_pair_activity import PairActivityEvaluationV31, RawActivityCoverageV31, activity_hash


class ActivityRuntimeIntegrityError(ValueError):
    """Bound source facts or immutable receipts disagree."""


def unavailable_activity(reason: str, *, status: str = "UNBOUND") -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason,
        "replay_required": True,
        "hypothesis_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }


def _event_payload(event: Any) -> dict[str, Any]:
    payload = asdict(event) if is_dataclass(event) else dict(event)
    # A raw ALLOWED fact may describe the source's permission, but persistence
    # never transfers it to the derived activity contract.
    return json.loads(json.dumps(payload, default=lambda value: value.isoformat()))


class PostgresActivityRuntime:
    def __init__(
        self,
        *,
        dsn: str,
        binding: ActivityRuntimeBindingV1,
        checkpoint_provider: Callable[[], ActivityCoverageCheckpointV1 | None],
        clock: Callable[[], datetime] | None = None,
        after_evaluations: Callable[[], None] | None = None,
    ) -> None:
        self._dsn = dsn
        self.binding = ActivityRuntimeBindingV1.model_validate(binding.model_dump(mode="json"))
        self._checkpoint_provider = checkpoint_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._after_evaluations = after_evaluations
        self._record_failure: str | None = None

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self._dsn,
            connect_timeout=2,
            options="-c statement_timeout=5000 -c lock_timeout=3000",
            row_factory=dict_row,
        )

    def _lock(self, connection: psycopg.Connection) -> Mapping[str, Any]:
        connection.execute(
            "INSERT INTO public.pair_activity_ledgers_v31(ledger_id,binding_hash,binding) "
            "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (self.binding.ledger_id, self.binding.binding_hash, Jsonb(self.binding.model_dump(mode="json"))),
        )
        row = connection.execute(
            "SELECT * FROM public.pair_activity_ledgers_v31 WHERE ledger_id=%s FOR UPDATE",
            (self.binding.ledger_id,),
        ).fetchone()
        if (
            row is None
            or row["binding_hash"] != self.binding.binding_hash
            or row["binding"] != self.binding.model_dump(mode="json")
        ):
            raise ActivityRuntimeIntegrityError("ACTIVITY_LEDGER_BINDING_CONFLICT")
        return row

    def _read_events(self, connection: psycopg.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT payload FROM public.pair_activity_raw_v31 WHERE ledger_id=%s "
            "ORDER BY occurred_at,raw_event_id LIMIT %s",
            (self.binding.ledger_id, self.binding.maximum_ledger_events + 1),
        ).fetchall()
        if len(rows) > self.binding.maximum_ledger_events:
            raise ActivityRuntimeIntegrityError("ACTIVITY_LEDGER_CAPACITY_EXCEEDED")
        return [row["payload"] for row in rows]

    def record(self, event: Any) -> None:
        """Persist a producer fact before its service snapshot can claim coverage.

        Any failed write latches the runtime unavailable until explicit worker
        recovery; continuing to hash its remaining buffer cannot heal data loss.
        """
        if self._record_failure:
            return
        try:
            self.append((event,))
        except (psycopg.Error, ValueError, TypeError):
            self._record_failure = "RAW_DURABILITY_WRITE_FAILED"

    def append(self, events: Iterable[Any]) -> None:
        incoming = [_event_payload(event) for event in events]
        with self._connect() as connection:
            self._lock(connection)
            prior = self._read_events(connection)
            normalized = normalize_pair_activity_observations([*prior, *incoming])
            if any(item.identity_basis != "SOURCE_OBSERVATION_ID" for item in normalized.logical_observations):
                raise ActivityRuntimeIntegrityError("RAW_SOURCE_OBSERVATION_IDENTITY_UNBOUND")
            if normalized.raw_event_count > self.binding.maximum_ledger_events:
                raise ActivityRuntimeIntegrityError("ACTIVITY_LEDGER_CAPACITY_EXCEEDED")
            if any(item.deployment_id != self.binding.deployment_id for item in normalized.raw_observations):
                raise ActivityRuntimeIntegrityError("RAW_DEPLOYMENT_BINDING_MISMATCH")
            if any(item.occurred_at_utc < self.binding.window_start_utc for item in normalized.raw_observations):
                raise ActivityRuntimeIntegrityError("RAW_PRECEDES_BOUND_LEDGER")
            payloads = {pair_activity_raw_event_id(event): event for event in [*prior, *incoming]}
            prior_ids = {pair_activity_raw_event_id(event) for event in prior}
            added_ids = {item.raw_event_id for item in normalized.raw_observations} - prior_ids
            added = 0
            for item in normalized.raw_observations:
                if item.raw_event_id not in added_ids:
                    continue
                result = connection.execute(
                    "INSERT INTO public.pair_activity_raw_v31(ledger_id,raw_event_id,occurred_at,payload) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        self.binding.ledger_id,
                        item.raw_event_id,
                        item.occurred_at_utc,
                        Jsonb(payloads[item.raw_event_id]),
                    ),
                )
                added += result.rowcount
            for observation in normalized.logical_observations:
                if not added_ids.intersection(observation.source_raw_event_ids):
                    continue
                connection.execute(
                    "INSERT INTO public.pair_activity_observations_v31(ledger_id,observation_id,payload) "
                    "VALUES (%s,%s,%s) ON CONFLICT (ledger_id,observation_id) DO UPDATE SET payload=EXCLUDED.payload",
                    (self.binding.ledger_id, observation.observation_id, Jsonb(observation.model_dump(mode="json"))),
                )
            if added:
                connection.execute(
                    "UPDATE public.pair_activity_ledgers_v31 SET revision=revision+%s WHERE ledger_id=%s",
                    (added, self.binding.ledger_id),
                )

    def _coverage(
        self,
        checkpoint: ActivityCoverageCheckpointV1 | None,
        *,
        raw_hash: str,
        raw_count: int,
        decision_at: datetime,
    ) -> tuple[RawActivityCoverageV31, str | None]:
        reason = None
        status = "UNKNOWN"
        end = decision_at
        if checkpoint is None:
            reason = "RAW_COVERAGE_CHECKPOINT_UNBOUND"
        elif (
            checkpoint.binding_hash != self.binding.binding_hash
            or checkpoint.attestor_id != self.binding.coverage_attestor_id
            or checkpoint.window_start_utc != self.binding.window_start_utc
        ):
            reason = "RAW_COVERAGE_CHECKPOINT_BINDING_MISMATCH"
        else:
            status, end = checkpoint.status, checkpoint.window_end_utc
            if checkpoint.expected_raw_hash != raw_hash or checkpoint.expected_raw_count != raw_count:
                status, reason = "INCOMPLETE", "RAW_COVERAGE_EXPECTED_POPULATION_MISMATCH"
        return RawActivityCoverageV31(
            status=status,
            ledger_id=self.binding.ledger_id,
            deployment_id=self.binding.deployment_id,
            window_start_utc=self.binding.window_start_utc,
            window_end_utc=end,
            source_ledger_hash=raw_hash if status == "COMPLETE" else None,
        ), reason

    def evaluate(self, *, trigger: str = "SERVICE_SNAPSHOT") -> dict[str, Any]:
        if self._record_failure:
            return unavailable_activity(self._record_failure, status="RECOVERY_REQUIRED")
        decision_at = self._clock()
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("runtime clock must be timezone aware")
        checkpoint = self._checkpoint_provider()
        if checkpoint is not None:
            checkpoint = ActivityCoverageCheckpointV1.model_validate(checkpoint.model_dump(mode="json"))
        with self._connect() as connection:
            ledger = self._lock(connection)
            if ledger["evaluated_through"] is not None and decision_at < ledger["evaluated_through"]:
                return unavailable_activity("STALE_DECISION_TIME", status="RECONCILIATION_REQUIRED")
            events = self._read_events(connection)
            normalized = normalize_pair_activity_observations(events)
            coverage, coverage_reason = self._coverage(
                checkpoint,
                raw_hash=normalized.raw_population_hash,
                raw_count=normalized.raw_event_count,
                decision_at=decision_at,
            )
            rows = connection.execute(
                "SELECT e.payload,f.payload AS frozen_payload FROM public.pair_activity_attachments_v31 a "
                "JOIN public.pair_activity_evaluations_v31 e "
                "ON e.ledger_id=a.ledger_id AND e.evaluation_id=a.evaluation_id "
                "LEFT JOIN public.pair_activity_evaluations_v31 f "
                "ON f.ledger_id=a.ledger_id AND f.evaluation_id=a.frozen_evaluation_id WHERE a.ledger_id=%s",
                (self.binding.ledger_id,),
            ).fetchall()
            previous = []
            for row in rows:
                payload = row["payload"]
                if not payload.get("admission_id") and payload.get("decision") != "RECONCILIATION_REQUIRED":
                    payload = row["frozen_payload"] or payload
                previous.append(PairActivityEvaluationV31.model_validate(payload))
            audit = build_pair_activity_audit(
                events,
                coverage=coverage,
                policy=self.binding.policy,
                decision_at_utc=decision_at,
                previous_evaluations=previous,
            )
            for item in audit.evaluations:
                payload = item.model_dump(mode="json")
                connection.execute(
                    "INSERT INTO public.pair_activity_evaluations_v31(ledger_id,evaluation_id,activity_id,payload) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (self.binding.ledger_id, item.evaluation_id, item.activity_id, Jsonb(payload)),
                )
                stored = connection.execute(
                    "SELECT payload FROM public.pair_activity_evaluations_v31 WHERE ledger_id=%s AND evaluation_id=%s",
                    (self.binding.ledger_id, item.evaluation_id),
                ).fetchone()
                if stored is None or stored["payload"] != payload:
                    raise ActivityRuntimeIntegrityError("IMMUTABLE_EVALUATION_COLLISION")
                connection.execute(
                    "INSERT INTO public.pair_activity_attachments_v31"
                    "(ledger_id,activity_id,evaluation_id,frozen_evaluation_id) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (ledger_id,activity_id) DO UPDATE SET evaluation_id=EXCLUDED.evaluation_id, "
                    "frozen_evaluation_id=COALESCE(pair_activity_attachments_v31.frozen_evaluation_id,"
                    "EXCLUDED.frozen_evaluation_id)",
                    (
                        self.binding.ledger_id,
                        item.activity_id,
                        item.evaluation_id,
                        item.evaluation_id if item.admission_id else None,
                    ),
                )
            if self._after_evaluations is not None:
                self._after_evaluations()
            prior_watermark = ledger["covered_through"]
            raw_watermark = max((item.occurred_at_utc for item in normalized.raw_observations), default=None)
            covered_through = prior_watermark
            if audit.coverage_status == "COMPLETE" and coverage.window_end_utc <= decision_at:
                covered_through = (
                    max(prior_watermark, coverage.window_end_utc) if prior_watermark else coverage.window_end_utc
                )
            report = {
                "status": "EVALUATED",
                "audit": audit.model_dump(mode="json"),
                "normalization": normalized.model_dump(mode="json"),
                "provenance": {
                    "binding_hash": self.binding.binding_hash,
                    "producer_id": self.binding.producer_id,
                    "source_scope_id": self.binding.source_scope_id,
                    "attestor_id": self.binding.coverage_attestor_id,
                    "checkpoint_id": checkpoint.checkpoint_id if checkpoint else None,
                    "coverage_reason": coverage_reason,
                    "source_revision": ledger["revision"],
                },
                "persistence": {
                    "status": "COMMITTED",
                    "boundary": "POSTGRES_ACTIVITY_EVALUATION_ATTACHMENT_WATERMARK",
                    "trigger": trigger,
                    "replay_from_utc": (
                        max(
                            self.binding.window_start_utc,
                            prior_watermark - timedelta(seconds=self.binding.recovery_overlap_seconds),
                        ).isoformat()
                        if prior_watermark
                        else self.binding.window_start_utc.isoformat()
                    ),
                    "replay_scope": "FULL_BOUND_LEDGER_SUPERSET_OF_OVERLAP",
                    "raw_watermark": raw_watermark.isoformat() if raw_watermark else None,
                    "covered_through_utc": covered_through.isoformat() if covered_through else None,
                },
                "replay_required": audit.coverage_status != "COMPLETE"
                or any(item.decision == "RECONCILIATION_REQUIRED" for item in audit.evaluations),
                "hypothesis_authority": False,
                "risk_authority": False,
                "execution_authority": False,
            }
            snapshot_id = activity_hash(
                [
                    self.binding.binding_hash,
                    ledger["revision"],
                    checkpoint.checkpoint_id if checkpoint else None,
                    audit.model_dump(mode="json"),
                ]
            )
            connection.execute(
                "INSERT INTO public.pair_activity_snapshots_v31(ledger_id,snapshot_id,revision,checkpoint,report) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    self.binding.ledger_id,
                    snapshot_id,
                    ledger["revision"],
                    Jsonb(checkpoint.model_dump(mode="json")) if checkpoint else None,
                    Jsonb(report),
                ),
            )
            connection.execute(
                "UPDATE public.pair_activity_ledgers_v31 SET evaluated_through=%s,raw_watermark=%s,covered_through=%s WHERE ledger_id=%s",
                (decision_at, raw_watermark, covered_through, self.binding.ledger_id),
            )
            stored_snapshot = connection.execute(
                "SELECT report FROM public.pair_activity_snapshots_v31 WHERE ledger_id=%s AND snapshot_id=%s",
                (self.binding.ledger_id, snapshot_id),
            ).fetchone()
            if stored_snapshot is None or stored_snapshot["report"].get("audit") != report["audit"]:
                raise ActivityRuntimeIntegrityError("IMMUTABLE_SNAPSHOT_COLLISION")
            if any(
                stored_snapshot["report"].get(key) is not False
                for key in ("hypothesis_authority", "risk_authority", "execution_authority")
            ):
                raise ActivityRuntimeIntegrityError("SNAPSHOT_AUTHORITY_VIOLATION")
            # Retry/restart returns the receipt actually committed originally,
            # including its trigger and replay boundary, rather than a new view
            # masquerading under the same immutable snapshot identity.
            report = stored_snapshot["report"]
        return report

    def snapshot(self) -> dict[str, Any]:
        try:
            return self.evaluate()
        except (psycopg.Error, ValueError, TypeError, OSError):
            return unavailable_activity("DURABLE_ACTIVITY_EVALUATION_FAILED", status="RECOVERY_REQUIRED")
