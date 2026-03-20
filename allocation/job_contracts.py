"""
Worker & Allocation Job Contracts — P1-10
==========================================
Declares the behavioral contract for each worker/allocation job:
  - Idempotency classification (IDEMPOTENT, DEDUP_REQUIRED, NON_RETRYABLE)
  - Output scope (ADVISORY, CONSTRAINT, MUTATION)
  - Retry safety (SAFE, REQUIRES_DEDUP, UNSAFE)
  - Expected side-effects

This is a **declarative** module — no execution logic.
Worker runners import and consult this contract before job dispatch.

Zone: allocation + worker — constraint layer, NOT verdict authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.redis_keys import (
    WORKER_BACKTEST_INPUT,
    WORKER_BACKTEST_RESULT,
    WORKER_MC_INPUT,
    WORKER_MC_RESULT,
    WORKER_REGIME_INPUT,
    WORKER_REGIME_RESULT,
)


class IdempotencyClass(StrEnum):
    """How safe is re-execution of this job?"""

    IDEMPOTENT = "IDEMPOTENT"  # Multiple runs produce same result (overwrite semantics)
    DEDUP_REQUIRED = "DEDUP_REQUIRED"  # Re-execution may produce duplicates or side-effects
    NON_RETRYABLE = "NON_RETRYABLE"  # Must not be retried (e.g. already-spent budget)


class OutputScope(StrEnum):
    """What kind of data does this job produce?"""

    ADVISORY = "ADVISORY"  # Metrics, analytics — no downstream authority
    CONSTRAINT = "CONSTRAINT"  # Risk/allocation constraints consumed by execution gate
    CONFIG_MUTATION = "CONFIG_MUTATION"  # Writes to config files/keys (requires ownership contract)


class RetrySafety(StrEnum):
    """Is the job safe to retry without dedup guard?"""

    SAFE = "SAFE"  # Overwrite semantics, safe to retry
    REQUIRES_DEDUP = "REQUIRES_DEDUP"  # Needs idempotency check before retry
    UNSAFE = "UNSAFE"  # Not safe to retry without manual intervention


@dataclass(frozen=True)
class WorkerJobContract:
    """Declarative behavioral contract for a worker job."""

    job_name: str
    module_path: str
    idempotency: IdempotencyClass
    output_scope: OutputScope
    retry_safety: RetrySafety
    reads_from: tuple[str, ...] = ()  # env vars, Redis keys, files
    writes_to: tuple[str, ...] = ()  # Redis keys, files, streams
    max_retries: int = 0
    description: str = ""
    boundary_notes: tuple[str, ...] = ()  # Authority boundary warnings


# ── Registered contracts ──────────────────────────────────────────────────────

WORKER_JOB_CONTRACTS: dict[str, WorkerJobContract] = {
    "montecarlo": WorkerJobContract(
        job_name="montecarlo",
        module_path="services.worker.montecarlo_job",
        idempotency=IdempotencyClass.IDEMPOTENT,
        output_scope=OutputScope.ADVISORY,
        retry_safety=RetrySafety.SAFE,
        reads_from=(
            "MONTE_CARLO_RETURN_MATRIX",
            "MONTE_CARLO_RETURN_MATRIX_FILE",
            WORKER_MC_INPUT,
        ),
        writes_to=(
            WORKER_MC_RESULT,
            "storage/snapshots/worker/montecarlo_latest.json",
        ),
        description="Monte Carlo simulation on return matrix. Overwrite-safe.",
    ),
    "nightly_backtest": WorkerJobContract(
        job_name="nightly_backtest",
        module_path="services.worker.nightly_backtest",
        idempotency=IdempotencyClass.IDEMPOTENT,
        output_scope=OutputScope.ADVISORY,
        retry_safety=RetrySafety.SAFE,
        reads_from=(
            "BACKTEST_TRADE_RETURNS",
            "BACKTEST_TRADE_RETURNS_FILE",
            WORKER_BACKTEST_INPUT,
        ),
        writes_to=(
            WORKER_BACKTEST_RESULT,
            "storage/snapshots/worker/nightly_backtest_latest.json",
        ),
        description="Nightly backtest evaluation. Overwrite-safe.",
    ),
    "regime_recalibration": WorkerJobContract(
        job_name="regime_recalibration",
        module_path="services.worker.regime_recalibration",
        idempotency=IdempotencyClass.IDEMPOTENT,
        output_scope=OutputScope.CONFIG_MUTATION,
        retry_safety=RetrySafety.SAFE,
        reads_from=(
            "REGIME_VR_VALUES",
            "REGIME_VR_VALUES_FILE",
            WORKER_REGIME_INPUT,
        ),
        writes_to=(
            WORKER_REGIME_RESULT,
            "storage/snapshots/worker/regime_recalibration_latest.json",
            "config/thresholds.auto.json",
        ),
        description="Regime recalibration + auto-tuner. Writes config/thresholds.auto.json.",
        boundary_notes=(
            "MEDIUM: writes config/thresholds.auto.json — filesystem config mutation. "
            "Downstream analysis layers read this file. Ownership contract: "
            "only regime_recalibration worker may write this file.",
        ),
    ),
}


@dataclass(frozen=True)
class AllocationJobContract:
    """Declarative behavioral contract for the allocation path."""

    job_name: str = "allocation"
    idempotency: IdempotencyClass = IdempotencyClass.DEDUP_REQUIRED
    output_scope: OutputScope = OutputScope.CONSTRAINT
    retry_safety: RetrySafety = RetrySafety.REQUIRES_DEDUP
    reads_from: tuple[str, ...] = (
        "signal:registry:id:{signal_id}",
        "AccountRepository (in-memory)",
    )
    writes_to: tuple[str, ...] = (
        "execution:queue (Redis Stream)",
        "allocation:audit (Redis Stream + JSONL file)",
    )
    max_retries: int = 3
    description: str = (
        "Multi-account allocation with per-account risk sizing. "
        "Produces execution plans as constraints. "
        "Requires dedup guard on request_id to prevent duplicate execution pushes."
    )
    boundary_invariants: tuple[str, ...] = (
        "MUST NOT mutate signal direction or constitutional verdict.",
        "MUST NOT read account balance into signal payload.",
        "MUST NOT execute trades — only produces execution plans.",
        "MUST clamp risk per account profile, never inflate.",
    )


ALLOCATION_CONTRACT = AllocationJobContract()


def get_worker_contract(job_name: str) -> WorkerJobContract | None:
    """Look up the declared contract for a worker job."""
    return WORKER_JOB_CONTRACTS.get(job_name)


def validate_job_name(job_name: str) -> bool:
    """Return True if the job name has a registered contract."""
    return job_name in WORKER_JOB_CONTRACTS
