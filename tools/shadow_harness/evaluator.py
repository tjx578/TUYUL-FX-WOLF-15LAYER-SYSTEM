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

Exact-S is a separate *dependent* acceptance (``EXACT_S_ACCEPTED``). Its only
authority is the owner-frozen verifier (``R9_BINDING_MODE``)::

    verify_r9_envelope_v1(r9_envelope, r9_artifact_bytes).exact_s_accepted

computed over the R9 envelope JSON and the R9 artifact bytes supplied to this
run. A missing envelope or missing bytes is never accepted, and a raw-bytes hash
match alone no longer accepts. ``EXACT_S_ACCEPTED`` is true only when that
verdict is true, at least one candidate exists, and every candidate has exactly
one ``MEASURED`` exact-S bound to the verified envelope: ``exact_s_id ==
snapshot_s.snapshot_id``, ``exact_s_sha256 == snapshot_s.snapshot_sha256`` and
``r9_artifact_sha256 == artifact_sha256``. The binding can only narrow the
verifier's verdict, never widen it. Absent or ``NOT_MEASURED`` exact-S can never
make it true, and the harness never fabricates an exact-S.

``shadow_acceptance_passed`` is the integration-level final result
(``FINAL_NATURAL_SHADOW_ACCEPTANCE`` / ``DEMO_PRECONDITION``), DERIVED only
(:func:`derive_shadow_acceptance_blockers`) and rejected if supplied::

    shadow_acceptance_passed = gate_passed AND EXACT_S_ACCEPTED AND r9_envelope_frozen

``gate_passed`` keeps its five-flag meaning, so ``gate_passed = true`` with
``EXACT_S_ACCEPTED = false`` yields ``shadow_acceptance_passed = false``.
``r9_envelope_status = FROZEN`` comes from :class:`R9EnvelopePin`, which exists
only after the schema document passed the policy pin at load (policy 1.4.0);
a document that is not frozen or does not match the pin rejects the input.

Natural candidates are 0..N per symbol; a symbol without a candidate is
reported with the policy's no-candidate status (``WAIT``) and nothing is
fabricated for it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from contracts.r9_envelope_v1 import (
    R9EnvelopeV1,
    R9EnvelopeVerdictV1,
    R9SnapshotIdentityV1,
    verify_r9_envelope_v1,
)
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
    R9EnvelopePin,
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
ExactSEvaluation = Literal[
    "ABSENT",
    "AMBIGUOUS",
    "NOT_MEASURED",
    "R9_ENVELOPE_NOT_ACCEPTED",
    "R9_ARTIFACT_NOT_BOUND",
    "SNAPSHOT_S_NOT_BOUND",
    "R9_ENVELOPE_BOUND",
]
R9EnvelopeInput = Literal["NOT_SUPPLIED", "UNPARSEABLE", "PARSED"]

R9_BINDING_MODE: Final = "R9_ENVELOPE_V1_VERIFIER_VERDICT_ONLY"
"""EXACT_S acceptance comes only from ``verify_r9_envelope_v1(envelope, artifact_bytes).exact_s_accepted``
(frozen ``contracts/r9_envelope_v1.py``). The harness never accepts on a hash match of its own."""

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
"""Components the frozen R9 artifact envelope carries (``R9EnvelopeV1``: source_artifact, artifact_sha256,
snapshot_s, collect, import, active_readback, capability, direct_receipt). The harness does not redefine the
envelope; it parses and verifies it only through ``contracts/r9_envelope_v1.py``."""

R9_ENVELOPE_FROZEN_STATUSES: Final[frozenset[str]] = frozenset({"FROZEN"})
"""``r9_envelope_status`` values that count as a frozen envelope (owner freeze 2026-09-28, pinned at load)."""

R9EnvelopeStatus = Literal["FROZEN"]
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
        if self.exact_s_accepted != (self.exact_s_evaluation == "R9_ENVELOPE_BOUND"):
            raise ValueError("exact_s_accepted is derived: true only for an exact-S bound to a verified R9 envelope")
        return self


class R9EnvelopeVerification(_Frozen):
    """What was supplied for R9 and the frozen verifier's verdict over it.

    ``verdict`` is the output of ``verify_r9_envelope_v1(envelope, artifact_bytes)`` and is ``None`` only when
    no envelope was supplied. ``exact_s_accepted`` is exactly ``verdict.exact_s_accepted`` (false without a
    verdict); nothing else can make it true. ``snapshot_s`` / ``envelope_artifact_sha256`` are read from the
    envelope only when it validates as ``R9EnvelopeV1``.
    """

    envelope_input: R9EnvelopeInput
    envelope_input_error: str | None
    envelope_sha256: str | None = Field(..., pattern=SHA256_PATTERN)
    artifact_supplied: bool
    artifact_sha256: str | None = Field(..., pattern=SHA256_PATTERN)
    verdict: R9EnvelopeVerdictV1 | None
    snapshot_s: R9SnapshotIdentityV1 | None
    envelope_artifact_sha256: str | None = Field(..., pattern=SHA256_PATTERN)
    exact_s_accepted: bool

    @model_validator(mode="after")
    def _verdict_is_the_only_authority(self) -> R9EnvelopeVerification:
        if (self.envelope_input == "NOT_SUPPLIED") != (self.envelope_sha256 is None):
            raise ValueError("envelope_sha256 is present exactly when an envelope was supplied")
        if (self.envelope_input == "NOT_SUPPLIED") != (self.verdict is None):
            raise ValueError("the verifier runs on every supplied envelope and on nothing else")
        if (self.envelope_input == "UNPARSEABLE") != (self.envelope_input_error is not None):
            raise ValueError("envelope_input_error is present exactly when the envelope is unparseable")
        if self.artifact_supplied != (self.artifact_sha256 is not None):
            raise ValueError("artifact_sha256 is present exactly when artifact bytes were supplied")
        if self.exact_s_accepted != (self.verdict is not None and self.verdict.exact_s_accepted):
            raise ValueError("exact_s_accepted is the verify_r9_envelope_v1 verdict only")
        if self.exact_s_accepted and (
            self.snapshot_s is None
            or self.envelope_artifact_sha256 is None
            or self.artifact_sha256 != self.envelope_artifact_sha256
        ):
            raise ValueError("an accepted verdict requires the envelope's snapshot_s and its verified artifact bytes")
        return self


class ExactSDependentAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    exact_s_accepted: bool = Field(..., alias="EXACT_S_ACCEPTED")
    rule: Literal["R9_ENVELOPE_V1_VERIFIED_AND_SNAPSHOT_S_BOUND"]
    r9_envelope_verification: R9EnvelopeVerification
    candidates: tuple[CandidateExactS, ...]

    @model_validator(mode="after")
    def _accepted_is_derived(self) -> ExactSDependentAcceptance:
        verification = self.r9_envelope_verification
        expected = (
            verification.exact_s_accepted
            and bool(self.candidates)
            and all(item.exact_s_accepted for item in self.candidates)
        )
        if self.exact_s_accepted != expected:
            raise ValueError("EXACT_S_ACCEPTED is derived: the R9 verifier verdict AND every candidate bound to S")
        bound = [item for item in self.candidates if item.exact_s_accepted]
        if bound and not verification.exact_s_accepted:
            raise ValueError("an exact-S can only bind to an R9 envelope the verifier accepted")
        s = verification.snapshot_s
        for item in bound:
            if s is None or (item.exact_s_id, item.exact_s_sha256, item.r9_artifact_sha256) != (
                s.snapshot_id,
                s.snapshot_sha256,
                verification.envelope_artifact_sha256,
            ):
                raise ValueError("a bound exact-S must equal the envelope's snapshot_s and artifact_sha256")
        return self


class ShadowAcceptance(BaseModel):
    """Explicit final-acceptance block. ``DEMO_PRECONDITION`` mirrors ``shadow_acceptance_passed``."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    label: Literal["FINAL_NATURAL_SHADOW_ACCEPTANCE"]
    demo_precondition: bool = Field(..., alias="DEMO_PRECONDITION")
    rule: Literal["GATE_PASSED_AND_EXACT_S_ACCEPTED_AND_R9_ENVELOPE_FROZEN"]
    r9_binding: Literal["R9_ENVELOPE_V1_VERIFIER_VERDICT_ONLY"]
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
    r9_envelope_pin: R9EnvelopePin
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
        if self.r9_envelope_status != self.r9_envelope_pin.envelope_status:
            raise ValueError("r9_envelope_status is derived from the verified R9 envelope pin")
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


def verify_r9_inputs(r9_envelope: bytes | None, r9_artifact: bytes | None) -> R9EnvelopeVerification:
    """Run the frozen verifier over the supplied R9 envelope JSON bytes and R9 artifact bytes. Never raises.

    The envelope is parsed strictly (duplicate keys / non-finite numbers are unparseable). An unparseable or
    non-object envelope is still given to the verifier, as an empty object, so the verdict records
    ``ENVELOPE_SCHEMA_INVALID``; ``r9_artifact`` is passed through as-is (``None`` = ``ARTIFACT_BYTES_REQUIRED``).
    """

    artifact_sha256 = sha256_hex(r9_artifact) if r9_artifact is not None else None
    if r9_envelope is None:
        return R9EnvelopeVerification(
            envelope_input="NOT_SUPPLIED",
            envelope_input_error=None,
            envelope_sha256=None,
            artifact_supplied=r9_artifact is not None,
            artifact_sha256=artifact_sha256,
            verdict=None,
            snapshot_s=None,
            envelope_artifact_sha256=None,
            exact_s_accepted=False,
        )
    input_error: str | None = None
    try:
        parsed = parse_json_strict(r9_envelope)
    except HarnessInputError as exc:
        parsed, input_error = None, exc.code
    if input_error is None and not isinstance(parsed, Mapping):
        input_error = "R9_ENVELOPE_NOT_OBJECT"
    payload: Mapping[str, object] = parsed if input_error is None and isinstance(parsed, Mapping) else {}
    verdict = verify_r9_envelope_v1(payload, r9_artifact)
    try:
        envelope: R9EnvelopeV1 | None = R9EnvelopeV1.model_validate(payload)
    except ValidationError:
        envelope = None
    return R9EnvelopeVerification(
        envelope_input="UNPARSEABLE" if input_error is not None else "PARSED",
        envelope_input_error=input_error,
        envelope_sha256=sha256_hex(r9_envelope),
        artifact_supplied=r9_artifact is not None,
        artifact_sha256=artifact_sha256,
        verdict=verdict,
        snapshot_s=envelope.snapshot_s if envelope is not None else None,
        envelope_artifact_sha256=envelope.artifact_sha256 if envelope is not None else None,
        exact_s_accepted=verdict.exact_s_accepted,
    )


def _bound_evaluation(single: ExactSCapture, verification: R9EnvelopeVerification) -> ExactSEvaluation:
    """Binding of one MEASURED exact-S to the verified envelope. Only narrows the verifier's verdict."""

    s = verification.snapshot_s
    if not verification.exact_s_accepted or s is None:
        return "R9_ENVELOPE_NOT_ACCEPTED"
    if single.r9_artifact_sha256 != verification.envelope_artifact_sha256:
        return "R9_ARTIFACT_NOT_BOUND"
    if (single.exact_s_id, single.exact_s_sha256) != (s.snapshot_id, s.snapshot_sha256):
        return "SNAPSHOT_S_NOT_BOUND"
    return "R9_ENVELOPE_BOUND"


def _exact_s_acceptance(bundle: ShadowCaptureBundle, verification: R9EnvelopeVerification) -> ExactSDependentAcceptance:
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
            else:
                evaluation = _bound_evaluation(single, verification)
            rows.append(
                CandidateExactS(
                    symbol=key,
                    candidate_id=candidate.candidate_id,
                    exact_s_evaluation=evaluation,
                    exact_s_id=single.exact_s_id if single else None,
                    exact_s_sha256=single.exact_s_sha256 if single else None,
                    r9_artifact_sha256=single.r9_artifact_sha256 if single else None,
                    exact_s_accepted=evaluation == "R9_ENVELOPE_BOUND",
                )
            )
    return ExactSDependentAcceptance.model_validate(
        {
            "EXACT_S_ACCEPTED": verification.exact_s_accepted
            and bool(rows)
            and all(row.exact_s_accepted for row in rows),
            "rule": "R9_ENVELOPE_V1_VERIFIED_AND_SNAPSHOT_S_BOUND",
            "r9_envelope_verification": verification,
            "candidates": rows,
        }
    )


def _checked_pin(loaded: LoadedPolicy, pin: R9EnvelopePin) -> R9EnvelopePin:
    policy = loaded.policy
    expected = (
        policy.r9_envelope_schema_relpath,
        policy.r9_envelope_status,
        policy.r9_envelope_frozen_schema_sha256,
        policy.r9_envelope_frozen_normative_span_sha256,
    )
    actual = (pin.schema_relpath, pin.envelope_status, pin.frozen_schema_sha256, pin.frozen_normative_span_sha256)
    if actual != expected:
        raise HarnessInputError("R9_ENVELOPE_PIN_MISMATCH", "R9 envelope pin does not match this policy")
    return pin


def evaluate_bundle(
    bundle: ShadowCaptureBundle,
    loaded: LoadedPolicy,
    universe: SymbolUniverse,
    *,
    r9_envelope_pin: R9EnvelopePin,
    bundle_sha256: str,
    r9_envelope: bytes | None,
    r9_artifact: bytes | None,
) -> ShadowHarnessReport:
    """Evaluate one bundle.

    ``r9_envelope_pin`` comes from :func:`tools.shadow_harness.manifest.load_r9_envelope_pin` (verified at load).
    ``r9_envelope`` (R9 envelope JSON bytes) and ``r9_artifact`` (R9 artifact bytes) must be passed explicitly;
    ``None`` means not supplied, and then EXACT_S can never be accepted.
    """

    policy = loaded.policy
    pin = _checked_pin(loaded, r9_envelope_pin)
    verification = verify_r9_inputs(r9_envelope, r9_artifact)
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
    dependent = _exact_s_acceptance(bundle, verification)
    blockers = derive_shadow_acceptance_blockers(
        gate_passed=not failures,
        exact_s_accepted=dependent.exact_s_accepted,
        r9_envelope_frozen=r9_envelope_is_frozen(pin.envelope_status),
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
        r9_envelope_pin=pin,
        r9_envelope_status=pin.envelope_status,
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
    r9_envelope_pin: R9EnvelopePin,
    r9_envelope: bytes | None,
    r9_artifact: bytes | None,
) -> ShadowHarnessReport:
    bundle = load_bundle_bytes(raw, loaded, universe)
    return evaluate_bundle(
        bundle,
        loaded,
        universe,
        r9_envelope_pin=r9_envelope_pin,
        bundle_sha256=sha256_hex(raw),
        r9_envelope=r9_envelope,
        r9_artifact=r9_artifact,
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
    "R9EnvelopeVerification",
    "ShadowAcceptance",
    "ShadowHarnessReport",
    "SymbolEvaluation",
    "derive_gate_failures",
    "derive_shadow_acceptance_blockers",
    "r9_envelope_is_frozen",
    "evaluate_bundle",
    "evaluate_bundle_bytes",
    "load_bundle_bytes",
    "verify_r9_inputs",
]
