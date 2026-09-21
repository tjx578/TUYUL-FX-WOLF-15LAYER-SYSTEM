"""Per-symbol isolation validation and cross-pair contamination detection.

Both are pure functions over an already-parsed :class:`ShadowCaptureBundle`.

* Isolation: every record sits under its own canonical symbol key, the key is a
  universe symbol, dry-run broker symbols match the frozen map, capture ids are
  unique per symbol, every lineage id a record for symbol X references is used
  only under X, and downstream records are anchored to same-symbol upstream
  records (no fabricated tradeplan without a candidate).
* Contamination: any lineage id, evidence id, evidence digest or exact price
  vector observed under more than one symbol. The count is the number of
  distinct contaminating values.
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
    ExactSCapture,
    RiskDryRunCapture,
    ShadowCaptureBundle,
    TradeplanCapture,
)
from tools.shadow_harness.manifest import SymbolUniverse

IsolationCode = Literal[
    "UNKNOWN_SYMBOL_KEY",
    "SYMBOL_KEY_MISMATCH",
    "BROKER_SYMBOL_MISMATCH",
    "DUPLICATE_CAPTURE_ID",
    "LINEAGE_SCOPE_VIOLATION",
    "UNANCHORED_LINEAGE",
]
ContaminationKind = Literal["LINEAGE_ID", "EVIDENCE_ID", "EVIDENCE_SHA256", "PRICE_VECTOR"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IsolationFinding(_Frozen):
    code: IsolationCode
    symbol_key: str
    capture_id: str | None
    detail: str


class CaptureRef(_Frozen):
    symbol: str
    capture_id: str


class ContaminationFinding(_Frozen):
    kind: ContaminationKind
    value: str
    symbols: tuple[str, ...]
    captures: tuple[CaptureRef, ...]


def iter_captures(bundle: ShadowCaptureBundle) -> Iterable[tuple[str, Capture]]:
    for key in sorted(bundle.captures_by_symbol):
        for capture in bundle.captures_by_symbol[key]:
            yield key, capture


def _evidence_ids(capture: Capture) -> tuple[str, ...]:
    ids = [capture.capture_id]
    if isinstance(capture, CandidateCapture):
        ids.append(capture.candidate_id)
    elif isinstance(capture, ExactSCapture):
        ids.append(capture.exact_s_id)
    elif isinstance(capture, BrokerAdaptationDryRunCapture):
        ids.append(capture.adaptation_id)
    elif isinstance(capture, RiskDryRunCapture):
        ids.append(capture.risk_evaluation_id)
    return tuple(ids)


def _evidence_digests(capture: Capture) -> tuple[str, ...]:
    if isinstance(capture, ExactSCapture):
        return (capture.evidence_sha256, capture.exact_s_sha256)
    return (capture.evidence_sha256,)


def _normalise_price(value: Decimal) -> str:
    normalised = value.normalize()
    return format(normalised, "f")


def price_vector(capture: Capture) -> str | None:
    """Exact, order-independent price vector of one capture, or ``None`` when it carries no prices."""

    points = capture.price_points()
    if not points:
        return None
    return "|".join(f"{point.name}={_normalise_price(point.value)}" for point in sorted(points, key=lambda p: p.name))


def _index(bundle: ShadowCaptureBundle) -> dict[tuple[ContaminationKind, str], list[CaptureRef]]:
    index: dict[tuple[ContaminationKind, str], list[CaptureRef]] = defaultdict(list)
    for _key, capture in iter_captures(bundle):
        ref = CaptureRef(symbol=capture.symbol, capture_id=capture.capture_id)
        values: list[tuple[ContaminationKind, str]] = []
        values.extend(("LINEAGE_ID", value) for _, value in capture.lineage.present())
        values.extend(("EVIDENCE_ID", value) for value in _evidence_ids(capture))
        values.extend(("EVIDENCE_SHA256", value) for value in _evidence_digests(capture))
        vector = price_vector(capture)
        if vector is not None:
            values.append(("PRICE_VECTOR", vector))
        for item in dict.fromkeys(values):
            index[item].append(ref)
    return index


def detect_cross_pair_contamination(bundle: ShadowCaptureBundle) -> tuple[ContaminationFinding, ...]:
    findings: list[ContaminationFinding] = []
    for (kind, value), refs in sorted(_index(bundle).items()):
        symbols = tuple(sorted({ref.symbol for ref in refs}))
        if len(symbols) > 1:
            captures = tuple(sorted(set(refs), key=lambda ref: (ref.symbol, ref.capture_id)))
            findings.append(ContaminationFinding(kind=kind, value=value, symbols=symbols, captures=captures))
    return tuple(findings)


def validate_symbol_isolation(bundle: ShadowCaptureBundle, universe: SymbolUniverse) -> tuple[IsolationFinding, ...]:
    findings: list[IsolationFinding] = []
    universe_symbols = set(universe.symbols)
    lineage_owners: dict[str, set[str]] = defaultdict(set)
    for _key, capture in iter_captures(bundle):
        for _, value in capture.lineage.present():
            lineage_owners[value].add(capture.symbol)

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
            item.lineage.tradeplan_id for item in captures if isinstance(item, TradeplanCapture) and item.symbol == key
        }
        seen_ids: set[str] = set()
        for capture in captures:
            findings.extend(
                _record_findings(key, capture, universe, lineage_owners, seen_ids, candidate_anchors, tradeplan_anchors)
            )
            seen_ids.add(capture.capture_id)
    return tuple(findings)


def _record_findings(
    key: str,
    capture: Capture,
    universe: SymbolUniverse,
    lineage_owners: dict[str, set[str]],
    seen_ids: set[str],
    candidate_anchors: set[tuple[str | None, str | None]],
    tradeplan_anchors: set[str | None],
) -> list[IsolationFinding]:
    out: list[IsolationFinding] = []

    def add(code: IsolationCode, detail: str) -> None:
        out.append(IsolationFinding(code=code, symbol_key=key, capture_id=capture.capture_id, detail=detail))

    if capture.symbol != key:
        add("SYMBOL_KEY_MISMATCH", f"record symbol {capture.symbol} is filed under {key}")
    if capture.capture_id in seen_ids:
        add("DUPLICATE_CAPTURE_ID", "capture id repeats within the symbol")
    if isinstance(capture, BrokerAdaptationDryRunCapture):
        expected = universe.broker_symbol_for(capture.symbol)
        if expected != capture.broker_symbol:
            add("BROKER_SYMBOL_MISMATCH", f"broker symbol {capture.broker_symbol} is not mapped to {capture.symbol}")
    for name, value in capture.lineage.present():
        foreign = sorted(lineage_owners[value] - {capture.symbol})
        if foreign:
            add("LINEAGE_SCOPE_VIOLATION", f"{name} is also referenced under {', '.join(foreign)}")
    if isinstance(capture, ExactSCapture | TradeplanCapture):
        if (capture.lineage.lifecycle_id, capture.lineage.thesis_id) not in candidate_anchors:
            add("UNANCHORED_LINEAGE", "lifecycle/thesis does not match a same-symbol candidate")
    elif (
        isinstance(capture, BrokerAdaptationDryRunCapture | RiskDryRunCapture)
        and capture.lineage.tradeplan_id not in tradeplan_anchors
    ):
        add("UNANCHORED_LINEAGE", "tradeplan_id does not match a same-symbol tradeplan capture")
    return out


__all__ = [
    "CaptureRef",
    "ContaminationFinding",
    "IsolationFinding",
    "detect_cross_pair_contamination",
    "iter_captures",
    "price_vector",
    "validate_symbol_isolation",
]
