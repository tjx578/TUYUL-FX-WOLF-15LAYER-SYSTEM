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
  PAIR-scoped evidence id) contaminating values. Price-vector overlap and
  GLOBAL-scoped evidence reuse are DIAGNOSTIC_ONLY and never counted here.
* ``BROKER_SUBMIT`` - number of dry-run captures that attempted a broker submit.

``gate_passed`` and ``gate_failures`` are DERIVED only, from those five flags
(:func:`derive_gate_failures`); a bundle that supplies either is rejected.

Exact-S is a separate *dependent* acceptance (``EXACT_S_ACCEPTED``): it is true
only when at least one candidate exists and every candidate has exactly one
``MEASURED`` exact-S bound to an R9 artifact actually supplied to this run.
Absent or ``NOT_MEASURED`` exact-S can never make it true, and the harness never
fabricates an exact-S. R9 binding is a raw-bytes sha256 match only
(``R9_BINDING_MODE``).

``shadow_acceptance_passed`` is the integration-level final result
(``FINAL_NATURAL_SHADOW_ACCEPTANCE`` / ``DEMO_PRECONDITION``), DERIVED only
(:func:`derive_shadow_acceptance_blockers`) and rejected if supplied::

    shadow_acceptance_passed = gate_passed AND EXACT_S_ACCEPTED AND r9_envelope_frozen

``gate_passed`` keeps its five-flag meaning, so ``gate_passed = true`` with
``EXACT_S_ACCEPTED = false`` yields ``shadow_acceptance_passed = false``.
Final SHADOW acceptance additionally requires the frozen R9 artifact envelope
(``R9_ENVELOPE_REQUIRED_COMPONENTS``). That envelope schema is not frozen yet,
so the policy pins ``r9_envelope_status = NOT_FROZEN`` and
``shadow_acceptance_passed`` is false even when the R9 hash matches.

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
    detect_global_evidence_reuse_diagnostics,
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

R9_BINDING_MODE: Final = "R9_ARTIFACT_SHA256_MATCH_ONLY"
"""Current R9 binding: a MEASURED exact-S binds when its ``r9_artifact_sha256`` equals the raw-bytes sha256
of an R9 artifact supplied to this run. This is necessary but NOT sufficient for final SHADOW acceptance."""

R9_ENVELOPE_REQUIRED_COMPONENTS: Final[tuple[str, ...]] = (
    "source_artifact=R9",
    "artifact_sha256",
    "snapshot_identity_S",
    "collect_identity",
    "import_identity",
    "ACTIVE_readback_identity",
    "capability_result",
    "direct_receipt_result",
)
"""Components the frozen R9 artifact envelope must carry before final SHADOW acceptance can pass.

This is a requirement list, not a schema: the harness does not define or parse the envelope. Until the
envelope schema is frozen, the policy pins ``r9_envelope_status = NOT_FROZEN`` and no status counts as frozen
(``R9_ENVELOPE_FROZEN_STATUSES`` is empty), so ``shadow_acceptance_passed`` cannot be true."""

R9_ENVELOPE_FROZEN_STATUSES: Final[frozenset[str]] = frozenset()
"""``r9_envelope_status`` values that count as a frozen envelope. Empty until the envelope schema is frozen."""

R9EnvelopeStatus = Literal["NOT_FROZEN"]
ShadowAcceptanceBlocker = Literal["GATE_NOT_PASSED", "EXACT_S_NOT_ACCEPTED", "R9_ENVELOPE_NOT_FROZEN"]
SHADOW_ACCEPTANCE_BLOCKER_ORDER: Final[tuple[ShadowAcceptanceBlocker, ...]] = (
    "GATE_NOT_PASSED",
    "EXACT_S_NOT_ACCEPTED",
    "R9_ENVELOPE_NOT_FROZEN",
)


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


def derive_shadow_acceptance_blockers(
    *, gate_passed: bool, exact_s_accepted: bool, r9_envelope_frozen: bool
) -> tuple[ShadowAcceptanceBlocker, ...]:
    """Ordered reasons final SHADOW acceptance fails; ``shadow_acceptance_passed`` is true exactly when empty."""

    passed: dict[ShadowAcceptanceBlocker, bool] = {
        "GATE_NOT_PASSED": gate_passed,
        "EXACT_S_NOT_ACCEPTED": exact_s_accepted,
        "R9_ENVELOPE_NOT_FROZEN": r9_envelope_frozen,
    }
    return tuple(item for item in SHADOW_ACCEPTANCE_BLOCKER_ORDER if not passed[item])


def r9_envelope_is_frozen(status: str) -> bool:
    return status in R9_ENVELOPE_FROZEN_STATUSES


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


class ShadowAcceptance(BaseModel):
    """Explicit final-acceptance block. ``DEMO_PRECONDITION`` mirrors ``shadow_acceptance_passed``."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    label: Literal["FINAL_NATURAL_SHADOW_ACCEPTANCE"]
    demo_precondition: bool = Field(..., alias="DEMO_PRECONDITION")
    rule: Literal["GATE_PASSED_AND_EXACT_S_ACCEPTED_AND_R9_ENVELOPE_FROZEN"]
    r9_binding: Literal["R9_ARTIFACT_SHA256_MATCH_ONLY"]
    r9_envelope_required_components: tuple[str, ...]
    blockers: tuple[ShadowAcceptanceBlocker, ...]


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
    r9_envelope_status: R9EnvelopeStatus
    shadow_acceptance_passed: bool
    shadow_acceptance: ShadowAcceptance
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

    @model_validator(mode="after")
    def _shadow_acceptance_is_derived(self) -> ShadowHarnessReport:
        blockers = derive_shadow_acceptance_blockers(
            gate_passed=self.gate_passed,
            exact_s_accepted=self.dependent_acceptance.exact_s_accepted,
            r9_envelope_frozen=r9_envelope_is_frozen(self.r9_envelope_status),
        )
        if self.shadow_acceptance.blockers != blockers:
            raise ValueError("shadow_acceptance.blockers is derived from gate_passed, EXACT_S_ACCEPTED, r9 envelope")
        if self.shadow_acceptance_passed != (not blockers):
            raise ValueError(
                "shadow_acceptance_passed is derived: gate_passed AND EXACT_S_ACCEPTED AND a frozen R9 envelope"
            )
        if self.shadow_acceptance.demo_precondition != self.shadow_acceptance_passed:
            raise ValueError("DEMO_PRECONDITION must equal shadow_acceptance_passed")
        if self.shadow_acceptance.r9_envelope_required_components != R9_ENVELOPE_REQUIRED_COMPONENTS:
            raise ValueError("r9_envelope_required_components must be R9_ENVELOPE_REQUIRED_COMPONENTS")
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
            f"{'/'.join(DERIVED_REPORT_FIELDS)} are derived by the harness and must not be supplied: "
            f"{', '.join(supplied)}",
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
    diagnostics = detect_price_overlap_diagnostics(bundle) + detect_global_evidence_reuse_diagnostics(bundle)
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
    dependent = _exact_s_acceptance(bundle, supplied_r9)
    blockers = derive_shadow_acceptance_blockers(
        gate_passed=not failures,
        exact_s_accepted=dependent.exact_s_accepted,
        r9_envelope_frozen=r9_envelope_is_frozen(policy.r9_envelope_status),
    )

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
        dependent_acceptance=dependent,
        r9_envelope_status=policy.r9_envelope_status,
        shadow_acceptance_passed=not blockers,
        shadow_acceptance=ShadowAcceptance.model_validate(
            {
                "label": "FINAL_NATURAL_SHADOW_ACCEPTANCE",
                "DEMO_PRECONDITION": not blockers,
                "rule": policy.shadow_acceptance_rule,
                "r9_binding": policy.r9_binding,
                "r9_envelope_required_components": R9_ENVELOPE_REQUIRED_COMPONENTS,
                "blockers": blockers,
            }
        ),
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
    "R9_BINDING_MODE",
    "R9_ENVELOPE_FROZEN_STATUSES",
    "R9_ENVELOPE_REQUIRED_COMPONENTS",
    "REPORT_SCHEMA",
    "SHADOW_ACCEPTANCE_BLOCKER_ORDER",
    "AcceptanceBlock",
    "CandidateExactS",
    "ExactSDependentAcceptance",
    "ShadowAcceptance",
    "ShadowHarnessReport",
    "SymbolEvaluation",
    "derive_gate_failures",
    "derive_shadow_acceptance_blockers",
    "r9_envelope_is_frozen",
    "evaluate_bundle",
    "evaluate_bundle_bytes",
    "load_bundle_bytes",
]
