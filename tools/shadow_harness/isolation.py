"""Per-symbol isolation validation and cross-pair contamination detection.

All are pure functions over an already-parsed :class:`ShadowCaptureBundle`.

* Isolation (per-symbol integrity): every symbol key is a universe symbol,
  dry-run broker symbols match the frozen map, capture ids are unique per
  symbol, and downstream records are anchored to same-symbol upstream records
  (no fabricated tradeplan without a candidate).
* Contamination (FAIL): identity-based, never numeric. The primary detector is
  lineage-based over ``symbol`` and the lineage ids in ``LINEAGE_FIELDS``: a
  record filed under another symbol's key, or any lineage id value observed
  under more than one symbol (e.g. an EURUSD capture carrying a GBPUSD
  ``thesis_id``). A secondary, scope-aware detector covers evidence ids /
  evidence digests reused across symbols: when any capture carrying the reused
  value declares ``evidence_scope = "PAIR"`` it is contamination
  (``SECONDARY_PAIR_SCOPED_EVIDENCE``). The count is the number of distinct
  contaminating values.
* Diagnostics (DIAGNOSTIC_ONLY, never a gate input):
  - identical price vectors across symbols (two pairs may legitimately share
    numeric prices);
  - evidence ids / digests reused across symbols where *every* carrying capture
    declares ``evidence_scope = "GLOBAL"``.
  The scope is a required capture field; a missing or unknown scope is rejected
  at parse time and is never treated as ``GLOBAL``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tools.shadow_harness.captures import (
    BrokerAdaptationDryRunCapture,
    CandidateCapture,
    Capture,
    EvidenceScope,
    ExactSCapture,
    RiskDryRunCapture,
    ShadowCaptureBundle,
    TradeplanCapture,
)
from tools.shadow_harness.manifest import SymbolUniverse

IsolationCode = Literal[
    "UNKNOWN_SYMBOL_KEY",
    "BROKER_SYMBOL_MISMATCH",
    "DUPLICATE_CAPTURE_ID",
    "UNANCHORED_LINEAGE",
]
ContaminationKind = Literal["SYMBOL", "LINEAGE_ID", "EVIDENCE_ID", "EVIDENCE_SHA256"]
EvidenceKind = Literal["EVIDENCE_ID", "EVIDENCE_SHA256"]
ContaminationDetector = Literal["PRIMARY_LINEAGE", "SECONDARY_PAIR_SCOPED_EVIDENCE"]
ContaminationCode = Literal["CROSS_PAIR_CONTAMINATION"]
DiagnosticKind = Literal[
    "PRICE_VECTOR_OVERLAP", "GLOBAL_SCOPED_EVIDENCE_ID_REUSE", "GLOBAL_SCOPED_EVIDENCE_SHA256_REUSE"
]

_GLOBAL_REUSE_KIND: dict[EvidenceKind, DiagnosticKind] = {
    "EVIDENCE_ID": "GLOBAL_SCOPED_EVIDENCE_ID_REUSE",
    "EVIDENCE_SHA256": "GLOBAL_SCOPED_EVIDENCE_SHA256_REUSE",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IsolationFinding(_Frozen):
    code: IsolationCode
    symbol_key: str
    capture_id: str | None
    detail: str


class CaptureRef(_Frozen):
    symbol_key: str
    symbol: str
    capture_id: str


class ContaminationFinding(_Frozen):
    code: ContaminationCode
    detector: ContaminationDetector
    kind: ContaminationKind
    fields: tuple[str, ...]
    value: str
    symbols: tuple[str, ...]
    evidence_scopes: tuple[EvidenceScope, ...]
    """Declared scopes of the carrying captures (secondary detector); empty for primary lineage findings."""
    captures: tuple[CaptureRef, ...]


class DiagnosticFinding(_Frozen):
    severity: Literal["DIAGNOSTIC_ONLY"]
    kind: DiagnosticKind
    fields: tuple[str, ...]
    value: str
    symbols: tuple[str, ...]
    captures: tuple[CaptureRef, ...]


class _EvidenceObservation(_Frozen):
    field: str
    ref: CaptureRef
    scope: EvidenceScope


def iter_captures(bundle: ShadowCaptureBundle) -> Iterable[tuple[str, Capture]]:
    for key in sorted(bundle.captures_by_symbol):
        for capture in bundle.captures_by_symbol[key]:
            yield key, capture


def _evidence_ids(capture: Capture) -> tuple[tuple[str, str], ...]:
    ids = [("capture_id", capture.capture_id)]
    if isinstance(capture, CandidateCapture):
        ids.append(("candidate_id", capture.candidate_id))
    elif isinstance(capture, ExactSCapture) and capture.exact_s_id is not None:
        ids.append(("exact_s_id", capture.exact_s_id))
    elif isinstance(capture, BrokerAdaptationDryRunCapture):
        ids.append(("adaptation_id", capture.adaptation_id))
    elif isinstance(capture, RiskDryRunCapture):
        ids.append(("risk_evaluation_id", capture.risk_evaluation_id))
    return tuple(ids)


def _evidence_digests(capture: Capture) -> tuple[tuple[str, str], ...]:
    digests = [("evidence_sha256", capture.evidence_sha256)]
    if isinstance(capture, ExactSCapture) and capture.exact_s_sha256 is not None:
        digests.append(("exact_s_sha256", capture.exact_s_sha256))
    return tuple(digests)


def _normalise_price(value: Decimal) -> str:
    normalised = value.normalize()
    return format(normalised, "f")


def price_vector(capture: Capture) -> str | None:
    """Exact, order-independent price vector of one capture, or ``None`` when it carries no prices."""

    points = capture.price_points()
    if not points:
        return None
    return "|".join(f"{point.name}={_normalise_price(point.value)}" for point in sorted(points, key=lambda p: p.name))


def _ref(key: str, capture: Capture) -> CaptureRef:
    return CaptureRef(symbol_key=key, symbol=capture.symbol, capture_id=capture.capture_id)


def _sorted_refs(refs: Iterable[CaptureRef]) -> tuple[CaptureRef, ...]:
    return tuple(sorted(set(refs), key=lambda ref: (ref.symbol_key, ref.symbol, ref.capture_id)))


def _span_symbols(refs: Iterable[CaptureRef]) -> tuple[str, ...]:
    listed = list(refs)
    return tuple(sorted({ref.symbol for ref in listed} | {ref.symbol_key for ref in listed}))


def _cross_pair_evidence_reuse(
    bundle: ShadowCaptureBundle,
) -> list[tuple[EvidenceKind, str, tuple[_EvidenceObservation, ...]]]:
    """Evidence ids / digests observed under more than one symbol, with every carrying capture's declared scope."""

    index: dict[tuple[EvidenceKind, str], list[_EvidenceObservation]] = defaultdict(list)
    for key, capture in iter_captures(bundle):
        ref = _ref(key, capture)
        entries: list[tuple[EvidenceKind, str, str]] = []
        entries.extend(("EVIDENCE_ID", field, value) for field, value in _evidence_ids(capture))
        entries.extend(("EVIDENCE_SHA256", field, value) for field, value in _evidence_digests(capture))
        for kind, field, value in entries:
            index[(kind, value)].append(_EvidenceObservation(field=field, ref=ref, scope=capture.evidence_scope))
    return [
        (kind, value, tuple(observed))
        for (kind, value), observed in sorted(index.items())
        if len({item.ref.symbol for item in observed}) > 1
    ]


def detect_cross_pair_contamination(bundle: ShadowCaptureBundle) -> tuple[ContaminationFinding, ...]:
    """Identity-based contamination only; numeric price equality is never contamination.

    Primary: lineage ids (always pair-bound) and records filed under another symbol's key.
    Secondary: evidence ids / digests reused across symbols where any carrying capture is ``PAIR``-scoped.
    Reuse where every carrying capture is ``GLOBAL``-scoped is not contamination
    (see :func:`detect_global_evidence_reuse_diagnostics`).
    """

    findings: list[ContaminationFinding] = []
    for key, capture in iter_captures(bundle):
        if capture.symbol != key:
            findings.append(
                ContaminationFinding(
                    code="CROSS_PAIR_CONTAMINATION",
                    detector="PRIMARY_LINEAGE",
                    kind="SYMBOL",
                    fields=("symbol",),
                    value=f"{capture.symbol}@{key}",
                    symbols=tuple(sorted({key, capture.symbol})),
                    evidence_scopes=(),
                    captures=(_ref(key, capture),),
                )
            )

    lineage_index: dict[str, list[tuple[str, CaptureRef]]] = defaultdict(list)
    for key, capture in iter_captures(bundle):
        ref = _ref(key, capture)
        for field, value in capture.lineage.present():
            lineage_index[value].append((field, ref))
    for value, observed in sorted(lineage_index.items()):
        refs = [ref for _field, ref in observed]
        if len({ref.symbol for ref in refs}) > 1:
            findings.append(
                ContaminationFinding(
                    code="CROSS_PAIR_CONTAMINATION",
                    detector="PRIMARY_LINEAGE",
                    kind="LINEAGE_ID",
                    fields=tuple(sorted({field for field, _ref in observed})),
                    value=value,
                    symbols=_span_symbols(refs),
                    evidence_scopes=(),
                    captures=_sorted_refs(refs),
                )
            )

    for kind, value, observations in _cross_pair_evidence_reuse(bundle):
        declared: set[EvidenceScope] = {item.scope for item in observations}
        scopes: tuple[EvidenceScope, ...] = tuple(sorted(declared))
        if "PAIR" in scopes:
            findings.append(
                ContaminationFinding(
                    code="CROSS_PAIR_CONTAMINATION",
                    detector="SECONDARY_PAIR_SCOPED_EVIDENCE",
                    kind=kind,
                    fields=tuple(sorted({item.field for item in observations})),
                    value=value,
                    symbols=_span_symbols(item.ref for item in observations),
                    evidence_scopes=scopes,
                    captures=_sorted_refs(item.ref for item in observations),
                )
            )
    return tuple(sorted(findings, key=lambda item: (item.detector, item.kind, item.value)))


def detect_global_evidence_reuse_diagnostics(bundle: ShadowCaptureBundle) -> tuple[DiagnosticFinding, ...]:
    """Evidence reused across symbols where every carrying capture is ``GLOBAL``-scoped. DIAGNOSTIC_ONLY."""

    findings: list[DiagnosticFinding] = []
    for kind, value, observations in _cross_pair_evidence_reuse(bundle):
        if all(item.scope == "GLOBAL" for item in observations):
            findings.append(
                DiagnosticFinding(
                    severity="DIAGNOSTIC_ONLY",
                    kind=_GLOBAL_REUSE_KIND[kind],
                    fields=tuple(sorted({item.field for item in observations})),
                    value=value,
                    symbols=tuple(sorted({item.ref.symbol for item in observations})),
                    captures=_sorted_refs(item.ref for item in observations),
                )
            )
    return tuple(findings)


def detect_price_overlap_diagnostics(bundle: ShadowCaptureBundle) -> tuple[DiagnosticFinding, ...]:
    """Identical price vectors across symbols. DIAGNOSTIC_ONLY: never contamination, never a gate input."""

    index: dict[str, list[CaptureRef]] = defaultdict(list)
    for key, capture in iter_captures(bundle):
        vector = price_vector(capture)
        if vector is not None:
            index[vector].append(_ref(key, capture))
    findings: list[DiagnosticFinding] = []
    for vector, refs in sorted(index.items()):
        symbols = tuple(sorted({ref.symbol for ref in refs}))
        if len(symbols) > 1:
            findings.append(
                DiagnosticFinding(
                    severity="DIAGNOSTIC_ONLY",
                    kind="PRICE_VECTOR_OVERLAP",
                    fields=("prices",),
                    value=vector,
                    symbols=symbols,
                    captures=_sorted_refs(refs),
                )
            )
    return tuple(findings)


def validate_symbol_isolation(bundle: ShadowCaptureBundle, universe: SymbolUniverse) -> tuple[IsolationFinding, ...]:
    findings: list[IsolationFinding] = []
    universe_symbols = set(universe.symbols)
    for key in sorted(bundle.captures_by_symbol):
        captures = bundle.captures_by_symbol[key]
        if key not in universe_symbols:
            findings.append(
                IsolationFinding(
                    code="UNKNOWN_SYMBOL_KEY",
                    symbol_key=key,
                    capture_id=None,
                    detail="symbol key is not in the pinned universe",
                )
            )
        candidate_anchors = {
            (item.lineage.lifecycle_id, item.lineage.thesis_id)
            for item in captures
            if isinstance(item, CandidateCapture) and item.symbol == key
        }
        tradeplan_anchors = {
            item.lineage.tradeplan_candidate_id
            for item in captures
            if isinstance(item, TradeplanCapture) and item.symbol == key
        }
        seen_ids: set[str] = set()
        for capture in captures:
            findings.extend(_record_findings(key, capture, universe, seen_ids, candidate_anchors, tradeplan_anchors))
            seen_ids.add(capture.capture_id)
    return tuple(findings)


def _record_findings(
    key: str,
    capture: Capture,
    universe: SymbolUniverse,
    seen_ids: set[str],
    candidate_anchors: set[tuple[str | None, str | None]],
    tradeplan_anchors: set[str | None],
) -> list[IsolationFinding]:
    out: list[IsolationFinding] = []

    def add(code: IsolationCode, detail: str) -> None:
        out.append(IsolationFinding(code=code, symbol_key=key, capture_id=capture.capture_id, detail=detail))

    if capture.capture_id in seen_ids:
        add("DUPLICATE_CAPTURE_ID", "capture id repeats within the symbol")
    if isinstance(capture, BrokerAdaptationDryRunCapture):
        expected = universe.broker_symbol_for(capture.symbol)
        if expected != capture.broker_symbol:
            add("BROKER_SYMBOL_MISMATCH", f"broker symbol {capture.broker_symbol} is not mapped to {capture.symbol}")
    if isinstance(capture, ExactSCapture | TradeplanCapture):
        if (capture.lineage.lifecycle_id, capture.lineage.thesis_id) not in candidate_anchors:
            add("UNANCHORED_LINEAGE", "lifecycle/thesis does not match a same-symbol candidate")
    elif (
        isinstance(capture, BrokerAdaptationDryRunCapture | RiskDryRunCapture)
        and capture.lineage.tradeplan_candidate_id not in tradeplan_anchors
    ):
        add("UNANCHORED_LINEAGE", "tradeplan_candidate_id does not match a same-symbol tradeplan capture")
    return out


__all__ = [
    "CaptureRef",
    "ContaminationFinding",
    "DiagnosticFinding",
    "IsolationFinding",
    "detect_cross_pair_contamination",
    "detect_global_evidence_reuse_diagnostics",
    "detect_price_overlap_diagnostics",
    "iter_captures",
    "price_vector",
    "validate_symbol_isolation",
]
