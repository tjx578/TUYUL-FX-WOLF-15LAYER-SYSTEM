"""Acceptance evaluation of one captured 30-pair SHADOW bundle.

The acceptance block contains exactly five keys:

* ``30_PAIR_EVALUATED`` - every universe symbol is present as a bundle key
  (an empty list is an evaluated ``WAIT`` symbol) and no other key exists.
* ``OPERATOR_PAIR_SELECTION`` - any operator-chosen pair in the header or on a
  candidate. Must be ``False``.
* ``OPERATOR_DIRECTION_SELECTION`` - any operator-chosen direction in the header
  or on a candidate/tradeplan. Must be ``False``.
* ``CROSS_PAIR_CONTAMINATION`` - number of distinct contaminating values.
* ``BROKER_SUBMIT`` - number of dry-run captures that attempted a broker submit.

Natural candidates are 0..N per symbol; a symbol without a candidate is
reported with the policy's no-candidate status (``WAIT``) and nothing is
fabricated for it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.shadow_harness import HARNESS_VERSION
from tools.shadow_harness.captures import (
    BrokerAdaptationDryRunCapture,
    CandidateCapture,
    RiskDryRunCapture,
    ShadowCaptureBundle,
    TradeplanCapture,
)
from tools.shadow_harness.isolation import (
    ContaminationFinding,
    IsolationFinding,
    detect_cross_pair_contamination,
    iter_captures,
    validate_symbol_isolation,
)
from tools.shadow_harness.manifest import (
    HarnessInputError,
    LoadedPolicy,
    SymbolUniverse,
    parse_json_strict,
    sha256_hex,
    summarise_validation_error,
)

REPORT_SCHEMA = "wolf15.shadow-harness.report.v1"
GateFailure = Literal[
    "NOT_30_PAIR_EVALUATED",
    "OPERATOR_PAIR_SELECTION",
    "OPERATOR_DIRECTION_SELECTION",
    "CROSS_PAIR_CONTAMINATION",
    "BROKER_SUBMIT",
    "ISOLATION_VIOLATION",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AcceptanceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    pair_30_evaluated: bool = Field(..., alias="30_PAIR_EVALUATED")
    operator_pair_selection: bool = Field(..., alias="OPERATOR_PAIR_SELECTION")
    operator_direction_selection: bool = Field(..., alias="OPERATOR_DIRECTION_SELECTION")
    cross_pair_contamination: int = Field(..., ge=0, alias="CROSS_PAIR_CONTAMINATION")
    broker_submit: int = Field(..., ge=0, alias="BROKER_SUBMIT")


class SymbolEvaluation(_Frozen):
    symbol: str
    broker_symbol: str
    status: Literal["CANDIDATE", "WAIT", "NOT_EVALUATED"]
    candidate_count: int = Field(..., ge=0)
    candidate_ids: tuple[str, ...]
    capture_counts: dict[str, int]


class ReportProvenance(_Frozen):
    harness_version: str
    run_id: str
    policy_version: str
    policy_sha256: str
    symbol_universe: str
    symbol_universe_sha256: str
    symbol_map_relpath: str
    bundle_sha256: str


class ShadowHarnessReport(_Frozen):
    report_schema: Literal["wolf15.shadow-harness.report.v1"]
    status: Literal["EVALUATED"]
    provenance: ReportProvenance
    acceptance: AcceptanceBlock
    gate_passed: bool
    gate_failures: tuple[GateFailure, ...]
    symbols: tuple[SymbolEvaluation, ...]
    isolation_findings: tuple[IsolationFinding, ...]
    contamination_findings: tuple[ContaminationFinding, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def load_bundle_bytes(raw: bytes, loaded: LoadedPolicy, universe: SymbolUniverse) -> ShadowCaptureBundle:
    payload = parse_json_strict(raw)
    if not isinstance(payload, Mapping):
        raise HarnessInputError("BUNDLE_NOT_OBJECT", "bundle must be a JSON object")
    try:
        bundle = ShadowCaptureBundle.model_validate(payload)
    except ValidationError as exc:
        raise HarnessInputError("BUNDLE_SCHEMA_INVALID", summarise_validation_error(exc)) from exc
    policy = loaded.policy
    header = bundle.header
    bindings = {
        "bundle_schema": (bundle.bundle_schema, policy.bundle_schema),
        "policy_sha256": (header.policy_sha256, loaded.policy_sha256),
        "policy_version": (header.policy_version, policy.policy_version),
        "symbol_universe": (header.symbol_universe, universe.universe_id),
        "symbol_universe_sha256": (header.symbol_universe_sha256, universe.canonical_sha256),
        "capture_schema_version": (header.capture_schema_version, policy.capture_schema_version),
    }
    mismatched = sorted(name for name, (actual, expected) in bindings.items() if actual != expected)
    if mismatched:
        raise HarnessInputError(
            "HEADER_BINDING_MISMATCH", f"bundle is not bound to this policy: {', '.join(mismatched)}"
        )
    return bundle


def evaluate_bundle(
    bundle: ShadowCaptureBundle,
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    *,
    bundle_sha256: str,
) -> ShadowHarnessReport:
    policy = loaded.policy
    isolation = validate_symbol_isolation(bundle, universe)
    contamination = detect_cross_pair_contamination(bundle)
    captures = [capture for _key, capture in iter_captures(bundle)]

    keys = set(bundle.captures_by_symbol)
    pair_30_evaluated = len(universe.symbols) == policy.expected_symbol_count and keys == set(universe.symbols)
    operator_pair = bool(bundle.header.operator_selected_symbols) or any(
        isinstance(item, CandidateCapture) and item.pair_selection_source == "OPERATOR" for item in captures
    )
    operator_direction = bool(bundle.header.operator_direction_overrides) or any(
        isinstance(item, CandidateCapture | TradeplanCapture) and item.direction_selection_source == "OPERATOR"
        for item in captures
    )
    broker_submit = sum(
        1
        for item in captures
        if isinstance(item, BrokerAdaptationDryRunCapture | RiskDryRunCapture) and item.broker_submit_attempted
    )
    acceptance = AcceptanceBlock.model_validate(
        {
            "30_PAIR_EVALUATED": pair_30_evaluated,
            "OPERATOR_PAIR_SELECTION": operator_pair,
            "OPERATOR_DIRECTION_SELECTION": operator_direction,
            "CROSS_PAIR_CONTAMINATION": len(contamination),
            "BROKER_SUBMIT": broker_submit,
        }
    )

    failures: list[GateFailure] = []
    if not pair_30_evaluated:
        failures.append("NOT_30_PAIR_EVALUATED")
    if operator_pair and not policy.operator_pair_selection_allowed:
        failures.append("OPERATOR_PAIR_SELECTION")
    if operator_direction and not policy.operator_direction_selection_allowed:
        failures.append("OPERATOR_DIRECTION_SELECTION")
    if contamination:
        failures.append("CROSS_PAIR_CONTAMINATION")
    if broker_submit != policy.required_broker_submit_count:
        failures.append("BROKER_SUBMIT")
    if isolation:
        failures.append("ISOLATION_VIOLATION")

    return ShadowHarnessReport(
        report_schema=REPORT_SCHEMA,
        status="EVALUATED",
        provenance=ReportProvenance(
            harness_version=HARNESS_VERSION,
            run_id=bundle.header.run_id,
            policy_version=policy.policy_version,
            policy_sha256=loaded.policy_sha256,
            symbol_universe=universe.universe_id,
            symbol_universe_sha256=universe.canonical_sha256,
            symbol_map_relpath=universe.source_relpath,
            bundle_sha256=bundle_sha256,
        ),
        acceptance=acceptance,
        gate_passed=not failures,
        gate_failures=tuple(failures),
        symbols=_symbol_evaluations(bundle, loaded, universe),
        isolation_findings=isolation,
        contamination_findings=contamination,
    )


def _symbol_evaluations(
    bundle: ShadowCaptureBundle, loaded: LoadedPolicy, universe: SymbolUniverse
) -> tuple[SymbolEvaluation, ...]:
    results: list[SymbolEvaluation] = []
    for binding in universe.bindings:
        symbol = binding.canonical_symbol
        captures = bundle.captures_by_symbol.get(symbol)
        if captures is None:
            results.append(
                SymbolEvaluation(
                    symbol=symbol,
                    broker_symbol=binding.broker_symbol,
                    status="NOT_EVALUATED",
                    candidate_count=0,
                    candidate_ids=(),
                    capture_counts={},
                )
            )
            continue
        candidates = [item for item in captures if isinstance(item, CandidateCapture) and item.symbol == symbol]
        counts = Counter(item.capture_kind for item in captures)
        results.append(
            SymbolEvaluation(
                symbol=symbol,
                broker_symbol=binding.broker_symbol,
                status="CANDIDATE" if candidates else loaded.policy.no_candidate_status,
                candidate_count=len(candidates),
                candidate_ids=tuple(sorted(item.candidate_id for item in candidates)),
                capture_counts=dict(sorted(counts.items())),
            )
        )
    return tuple(results)


def evaluate_bundle_bytes(raw: bytes, loaded: LoadedPolicy, universe: SymbolUniverse) -> ShadowHarnessReport:
    bundle = load_bundle_bytes(raw, loaded, universe)
    return evaluate_bundle(bundle, loaded, universe, bundle_sha256=sha256_hex(raw))


__all__ = [
    "REPORT_SCHEMA",
    "AcceptanceBlock",
    "ShadowHarnessReport",
    "SymbolEvaluation",
    "evaluate_bundle",
    "evaluate_bundle_bytes",
    "load_bundle_bytes",
]
