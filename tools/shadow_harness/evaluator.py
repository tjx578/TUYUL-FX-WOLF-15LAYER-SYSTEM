"""Acceptance evaluation of one captured 30-pair SHADOW bundle.

The acceptance block contains exactly five flags:

* ``30_PAIR_EVALUATED`` - every universe symbol is present as a bundle key
  (an empty list is an evaluated ``WAIT`` symbol), no other key exists, and no
  symbol has a per-symbol integrity (isolation) finding.
* ``OPERATOR_PAIR_SELECTION`` - any candidate attests an operator-chosen pair.
  Must be ``False``.
* ``OPERATOR_DIRECTION_SELECTION`` - any candidate/tradeplan attests an
  operator-chosen direction. Must be ``False``.
* ``CROSS_PAIR_CONTAMINATION`` - number of distinct identity-based (lineage /
  evidence id) contaminating values. Price-vector overlap is DIAGNOSTIC_ONLY and
  never counted here.
* ``BROKER_SUBMIT`` - number of dry-run captures that attempted a broker submit.

``gate_passed`` and ``gate_failures`` are DERIVED only, from those five flags
(:func:`derive_gate_failures`); a bundle that supplies either is rejected.

Exact-S is a separate *dependent* acceptance (``EXACT_S_ACCEPTED``): it is true
only when at least one candidate exists and every candidate has exactly one
``MEASURED`` exact-S bound to an R9 artifact actually supplied to this run.
Absent or ``NOT_MEASURED`` exact-S can never make it true, and the harness never
fabricates an exact-S.

Natural candidates are 0..N per symbol; a symbol without a candidate is
reported with the policy's no-candidate status (``WAIT``) and nothing is
fabricated for it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tools.shadow_harness import HARNESS_VERSION
from tools.shadow_harness.captures import (
    BUNDLE_HEADER_FIELDS,
    BUNDLE_MARKING,
    BUNDLE_SCHEMA_VERSION,
    DERIVED_REPORT_FIELDS,
    BrokerAdaptationDryRunCapture,
    BundleHeader,
    CandidateCapture,
    ExactSCapture,
    RiskDryRunCapture,
    ShadowCaptureBundle,
    TradeplanCapture,
)
from tools.shadow_harness.isolation import (
    ContaminationFinding,
    DiagnosticFinding,
    IsolationFinding,
    detect_cross_pair_contamination,
    detect_price_overlap_diagnostics,
    iter_captures,
    validate_symbol_isolation,
)
from tools.shadow_harness.manifest import (
    SHA256_PATTERN,
    HarnessInputError,
    HarnessPolicyV1,
    LoadedPolicy,
    SymbolUniverse,
    parse_json_strict,
    sha256_hex,
    summarise_validation_error,
)

REPORT_SCHEMA = "wolf15.shadow-harness.report.v1"
GateFlag = Literal[
    "30_PAIR_EVALUATED",
    "OPERATOR_PAIR_SELECTION",
    "OPERATOR_DIRECTION_SELECTION",
    "CROSS_PAIR_CONTAMINATION",
    "BROKER_SUBMIT",
]
GATE_FLAG_ORDER: Final[tuple[GateFlag, ...]] = (
    "30_PAIR_EVALUATED",
    "OPERATOR_PAIR_SELECTION",
    "OPERATOR_DIRECTION_SELECTION",
    "CROSS_PAIR_CONTAMINATION",
    "BROKER_SUBMIT",
)
ExactSEvaluation = Literal["ABSENT", "NOT_MEASURED", "R9_ARTIFACT_NOT_SUPPLIED", "AMBIGUOUS", "R9_BOUND"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AcceptanceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    pair_30_evaluated: bool = Field(..., alias="30_PAIR_EVALUATED")
    operator_pair_selection: bool = Field(..., alias="OPERATOR_PAIR_SELECTION")
    operator_direction_selection: bool = Field(..., alias="OPERATOR_DIRECTION_SELECTION")
    cross_pair_contamination: int = Field(..., ge=0, alias="CROSS_PAIR_CONTAMINATION")
    broker_submit: int = Field(..., ge=0, alias="BROKER_SUBMIT")


def derive_gate_failures(acceptance: AcceptanceBlock, policy: HarnessPolicyV1) -> tuple[GateFlag, ...]:
    """Deterministic, ordered (``GATE_FLAG_ORDER``) names of the acceptance flags that failed."""

    passed: dict[GateFlag, bool] = {
        "30_PAIR_EVALUATED": acceptance.pair_30_evaluated,
        "OPERATOR_PAIR_SELECTION": (not acceptance.operator_pair_selection) or policy.operator_pair_selection_allowed,
        "OPERATOR_DIRECTION_SELECTION": (not acceptance.operator_direction_selection)
        or policy.operator_direction_selection_allowed,
        "CROSS_PAIR_CONTAMINATION": acceptance.cross_pair_contamination == 0,
        "BROKER_SUBMIT": acceptance.broker_submit == policy.required_broker_submit_count,
    }
    return tuple(flag for flag in GATE_FLAG_ORDER if not passed[flag])


class CandidateExactS(_Frozen):
    symbol: str
    candidate_id: str
    exact_s_evaluation: ExactSEvaluation
    exact_s_id: str | None
    exact_s_sha256: str | None
    r9_artifact_sha256: str | None
    exact_s_accepted: bool

    @model_validator(mode="after")
    def _accepted_is_derived(self) -> CandidateExactS:
        if self.exact_s_accepted != (self.exact_s_evaluation == "R9_BOUND"):
            raise ValueError("exact_s_accepted is derived: true only for an R9-bound exact-S")
        return self


class ExactSDependentAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    exact_s_accepted: bool = Field(..., alias="EXACT_S_ACCEPTED")
    rule: Literal["R9_ARTIFACT_BOUND"]
    supplied_r9_artifact_sha256s: tuple[str, ...]
    candidates: tuple[CandidateExactS, ...]

    @model_validator(mode="after")
    def _accepted_is_derived(self) -> ExactSDependentAcceptance:
        expected = bool(self.candidates) and all(item.exact_s_accepted for item in self.candidates)
        if self.exact_s_accepted != expected:
            raise ValueError("EXACT_S_ACCEPTED is derived: missing or unbound exact-S never passes")
        return self


class SymbolEvaluation(_Frozen):
    symbol: str
    broker_symbol: str
    status: Literal["CANDIDATE", "WAIT", "NOT_EVALUATED"]
    candidate_count: int = Field(..., ge=0)
    candidate_ids: tuple[str, ...]
    capture_counts: dict[str, int]


class ReportProvenance(_Frozen):
    harness_version: str
    bundle_schema_version: Literal["shadow_capture_bundle/v1"]
    bundle_marking: tuple[Literal["IMPLEMENTATION_ONLY"], Literal["NON_CANONICAL"]]
    bundle_header: BundleHeader
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
    gate_failures: tuple[GateFlag, ...]
    dependent_acceptance: ExactSDependentAcceptance
    symbols: tuple[SymbolEvaluation, ...]
    isolation_findings: tuple[IsolationFinding, ...]
    contamination_findings: tuple[ContaminationFinding, ...]
    diagnostics: tuple[DiagnosticFinding, ...]

    @model_validator(mode="after")
    def _gate_is_derived(self) -> ShadowHarnessReport:
        ordered = tuple(flag for flag in GATE_FLAG_ORDER if flag in self.gate_failures)
        if self.gate_failures != ordered:
            raise ValueError("gate_failures must be unique and in GATE_FLAG_ORDER")
        if self.gate_passed != (not self.gate_failures):
            raise ValueError("gate_passed is derived: true exactly when gate_failures is empty")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def _find_derived_fields(value: Any, path: str) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in DERIVED_REPORT_FIELDS:
                yield child
            yield from _find_derived_fields(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _find_derived_fields(item, f"{path}[{index}]")


def _check_header_shape(payload: Mapping[str, Any]) -> None:
    header = payload.get("header")
    if not isinstance(header, Mapping):
        raise HarnessInputError("BUNDLE_HEADER_MISSING", "bundle must carry a header object")
    if header.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise HarnessInputError(
            "BUNDLE_SCHEMA_VERSION_UNKNOWN",
            f"header.schema_version must be {BUNDLE_SCHEMA_VERSION!r}",
        )
    missing = [name for name in BUNDLE_HEADER_FIELDS if name not in header]
    if missing:
        raise HarnessInputError("BUNDLE_HEADER_FIELD_MISSING", f"header is missing: {', '.join(missing)}")


def load_bundle_bytes(raw: bytes, loaded: LoadedPolicy, universe: SymbolUniverse) -> ShadowCaptureBundle:
    payload = parse_json_strict(raw)
    if not isinstance(payload, Mapping):
        raise HarnessInputError("BUNDLE_NOT_OBJECT", "bundle must be a JSON object")
    supplied = sorted(_find_derived_fields(payload, "$"))
    if supplied:
        raise HarnessInputError(
            "DERIVED_FIELD_SUPPLIED",
            f"gate_passed/gate_failures are derived by the harness and must not be supplied: {', '.join(supplied)}",
        )
    _check_header_shape(payload)
    try:
        bundle = ShadowCaptureBundle.model_validate(payload)
    except ValidationError as exc:
        raise HarnessInputError("BUNDLE_SCHEMA_INVALID", summarise_validation_error(exc)) from exc
    header = bundle.header
    bindings = {
        "schema_version": (header.schema_version, loaded.policy.bundle_schema),
        "configuration_digest": (header.configuration_digest, loaded.policy_sha256),
        "manifest_hash": (header.manifest_hash, universe.canonical_sha256),
    }
    mismatched = sorted(name for name, (actual, expected) in bindings.items() if actual != expected)
    if mismatched:
        raise HarnessInputError(
            "HEADER_BINDING_MISMATCH", f"bundle is not bound to this policy/universe: {', '.join(mismatched)}"
        )
    return bundle


def _validated_r9_digests(r9_artifact_sha256s: frozenset[str]) -> tuple[str, ...]:
    invalid = sorted(item for item in r9_artifact_sha256s if not re.fullmatch(SHA256_PATTERN, item))
    if invalid:
        raise HarnessInputError("R9_ARTIFACT_DIGEST_INVALID", "R9 artifact digests must be lowercase sha256 hex")
    return tuple(sorted(r9_artifact_sha256s))


def _exact_s_acceptance(bundle: ShadowCaptureBundle, supplied_r9: tuple[str, ...]) -> ExactSDependentAcceptance:
    supplied = set(supplied_r9)
    rows: list[CandidateExactS] = []
    for key in sorted(bundle.captures_by_symbol):
        captures = bundle.captures_by_symbol[key]
        exact_by_anchor: dict[tuple[str | None, str | None], list[ExactSCapture]] = {}
        for item in captures:
            if isinstance(item, ExactSCapture) and item.symbol == key:
                anchor = (item.lineage.lifecycle_id, item.lineage.thesis_id)
                exact_by_anchor.setdefault(anchor, []).append(item)
        candidates = [item for item in captures if isinstance(item, CandidateCapture) and item.symbol == key]
        for candidate in sorted(candidates, key=lambda item: item.candidate_id):
            matches = exact_by_anchor.get((candidate.lineage.lifecycle_id, candidate.lineage.thesis_id), [])
            single = matches[0] if len(matches) == 1 else None
            if not matches:
                evaluation: ExactSEvaluation = "ABSENT"
            elif single is None:
                evaluation = "AMBIGUOUS"
            elif single.exact_s_status == "NOT_MEASURED":
                evaluation = "NOT_MEASURED"
            elif single.r9_artifact_sha256 in supplied:
                evaluation = "R9_BOUND"
            else:
                evaluation = "R9_ARTIFACT_NOT_SUPPLIED"
            rows.append(
                CandidateExactS(
                    symbol=key,
                    candidate_id=candidate.candidate_id,
                    exact_s_evaluation=evaluation,
                    exact_s_id=single.exact_s_id if single else None,
                    exact_s_sha256=single.exact_s_sha256 if single else None,
                    r9_artifact_sha256=single.r9_artifact_sha256 if single else None,
                    exact_s_accepted=evaluation == "R9_BOUND",
                )
            )
    return ExactSDependentAcceptance.model_validate(
        {
            "EXACT_S_ACCEPTED": bool(rows) and all(row.exact_s_accepted for row in rows),
            "rule": "R9_ARTIFACT_BOUND",
            "supplied_r9_artifact_sha256s": supplied_r9,
            "candidates": rows,
        }
    )


def evaluate_bundle(
    bundle: ShadowCaptureBundle,
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    *,
    bundle_sha256: str,
    r9_artifact_sha256s: frozenset[str],
) -> ShadowHarnessReport:
    """Evaluate one bundle. ``r9_artifact_sha256s`` must be passed explicitly (empty = no R9 artifact supplied)."""

    policy = loaded.policy
    supplied_r9 = _validated_r9_digests(r9_artifact_sha256s)
    isolation = validate_symbol_isolation(bundle, universe)
    contamination = detect_cross_pair_contamination(bundle)
    diagnostics = detect_price_overlap_diagnostics(bundle)
    captures = [capture for _key, capture in iter_captures(bundle)]

    keys = set(bundle.captures_by_symbol)
    pair_30_evaluated = (
        len(universe.symbols) == policy.expected_symbol_count and keys == set(universe.symbols) and not isolation
    )
    operator_pair = any(
        isinstance(item, CandidateCapture) and item.pair_selection_source == "OPERATOR" for item in captures
    )
    operator_direction = any(
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
    failures = derive_gate_failures(acceptance, policy)

    return ShadowHarnessReport(
        report_schema=REPORT_SCHEMA,
        status="EVALUATED",
        provenance=ReportProvenance(
            harness_version=HARNESS_VERSION,
            bundle_schema_version=bundle.header.schema_version,
            bundle_marking=BUNDLE_MARKING,
            bundle_header=bundle.header,
            policy_version=policy.policy_version,
            policy_sha256=loaded.policy_sha256,
            symbol_universe=universe.universe_id,
            symbol_universe_sha256=universe.canonical_sha256,
            symbol_map_relpath=universe.source_relpath,
            bundle_sha256=bundle_sha256,
        ),
        acceptance=acceptance,
        gate_passed=not failures,
        gate_failures=failures,
        dependent_acceptance=_exact_s_acceptance(bundle, supplied_r9),
        symbols=_symbol_evaluations(bundle, loaded, universe),
        isolation_findings=isolation,
        contamination_findings=contamination,
        diagnostics=diagnostics,
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


def evaluate_bundle_bytes(
    raw: bytes,
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    *,
    r9_artifact_sha256s: frozenset[str],
) -> ShadowHarnessReport:
    bundle = load_bundle_bytes(raw, loaded, universe)
    return evaluate_bundle(
        bundle, loaded, universe, bundle_sha256=sha256_hex(raw), r9_artifact_sha256s=r9_artifact_sha256s
    )


__all__ = [
    "GATE_FLAG_ORDER",
    "REPORT_SCHEMA",
    "AcceptanceBlock",
    "CandidateExactS",
    "ExactSDependentAcceptance",
    "ShadowHarnessReport",
    "SymbolEvaluation",
    "derive_gate_failures",
    "evaluate_bundle",
    "evaluate_bundle_bytes",
    "load_bundle_bytes",
]
