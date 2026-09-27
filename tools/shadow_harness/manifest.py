"""Versioned harness policy and the pinned ``WOLF15_XM_30_V1`` symbol universe.

The universe is not redefined here. It is read, read-only, from the existing
frozen broker map ``ea_interface/wolf15_executor/broker_maps/xmglobal-mt5-10.csv``
(the same file used by ``execution/mt5_shadow_acceptance.py`` and
``scripts/audit_mt5_shadow_matrix.py``). Its canonical content hash is pinned in
the policy file, so any edit to the map is detected rather than absorbed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CANONICAL_SYMBOL_PATTERN: Final = r"^[A-Z]{6}$"
BROKER_SYMBOL_PATTERN: Final = r"^[A-Za-z0-9._#-]{1,32}$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_SYMBOL_MAP_HEADER: Final = ("canonical_symbol", "broker_symbol")

CAPTURE_KINDS: Final[tuple[str, ...]] = (
    "BROKER_ADAPTATION_DRY_RUN",
    "CANDIDATE",
    "EXACT_S",
    "RISK_DRY_RUN",
    "TRADEPLAN",
)
"""Every capture kind of ``wolf15.shadow-harness.capture.v1`` (sorted)."""

GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS: Final[tuple[str, ...]] = ()
"""Explicit allow-list of capture kinds that MAY declare ``evidence_scope = "GLOBAL"``. No default.

GLOBAL is reserved for system/global authority evidence with no pair-specific
strategy conclusion (R9 envelope, global safety state, governance authority
hash, policy registry, deployment/source binding, system-level reconciliation
capability). None of the existing capture kinds is such a kind: every one is
symbol-bound and lineage-bearing. The allow-list is therefore empty and GLOBAL
is allowed for no capture kind.
"""

GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS: Final[tuple[str, ...]] = CAPTURE_KINDS
"""Pair-specific strategy kinds (candidate/thesis/proof/box/target/lineage-bearing): GLOBAL rejects the bundle.

Must stay disjoint from :data:`GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS`.
"""

PAIR_BINDING_REQUIRED_CAPTURE_KINDS: Final[tuple[str, ...]] = ("CANDIDATE", "TRADEPLAN")
"""PAIR-scoped kinds that must bind canonical symbol + strategy lifecycle id + candidate/tradeplan revision identity."""

if set(GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS) & set(GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS):  # pragma: no cover
    raise RuntimeError("a pair-specific strategy capture kind can never be GLOBAL-allowed")

R9_ENVELOPE_SCHEMA_RELPATH: Final = "docs/governance/r9-envelope-v1.md"
"""Schema document of the owner-frozen ``R9EnvelopeV1`` (PR #517), read read-only at load."""

R9_ENVELOPE_FROZEN_SCHEMA_SHA256: Final = "10732eebab7e8a3a9270be6d378689e6160bd7a8087520ee2d86bf156e7588a2"
"""sha256 of the exact schema bytes the owner froze on 2026-09-28 (freeze record, section 8)."""

R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256: Final = "c9663fa7a752baa8f8723ef0241980d7fc9a55938ff480dc5703564e4e31b96f"
"""sha256 of the frozen normative span (``## 1. Purpose`` up to ``\\n## 8. Freeze record``), recomputed at load."""

_R9_NORMATIVE_SPAN_START: Final = b"## 1. Purpose"
_R9_NORMATIVE_SPAN_END: Final = b"\n## 8. Freeze record"
_R9_FREEZE_RECORD_KEY_WIDTH: Final = 31


class HarnessInputError(ValueError):
    """Fail-closed rejection of a policy, universe or evidence input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessInputError("DUPLICATE_JSON_KEY", f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise HarnessInputError("NON_FINITE_NUMBER", f"non-finite JSON number {name!r} is not allowed")


def parse_json_strict(raw: bytes) -> Any:
    """Parse JSON rejecting duplicate keys and non-finite numbers; floats become ``Decimal``."""

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HarnessInputError("NOT_UTF8", "input is not UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=Decimal,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise HarnessInputError("INVALID_JSON", f"invalid JSON at line {exc.lineno}") from exc


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not canonically serialisable: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic JSON encoding used for every hash in the harness."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode("ascii")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HarnessPolicyV1(BaseModel):
    """Every value the harness depends on. Nothing is defaulted in code."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_schema: Literal["wolf15.shadow-harness.policy.v1"]
    policy_version: str = Field(..., pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    symbol_universe: Literal["WOLF15_XM_30_V1"]
    expected_symbol_count: Literal[30]
    symbol_map_relpath: str = Field(..., min_length=1, max_length=256)
    symbol_map_canonical_sha256: str = Field(..., pattern=SHA256_PATTERN)
    bundle_schema: Literal["shadow_capture_bundle/v1"]
    capture_schema_version: Literal["wolf15.shadow-harness.capture.v1"]
    contamination_rule: Literal["LINEAGE_IDENTITY"]
    evidence_scope_rule: Literal["EXPLICIT_REQUIRED"]
    pair_scope_binding_rule: Literal["EXACT_CANONICAL_SYMBOL_AND_LIFECYCLE_AND_REVISION"]
    """PAIR: capture symbol == its bundle key; CANDIDATE/TRADEPLAN also bind lifecycle id + revision identity."""
    pair_binding_required_capture_kinds: list[str]
    global_scope_allowed_capture_kinds: list[str]
    """Explicit GLOBAL allow-list; must equal :data:`GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS` (currently empty)."""
    global_scope_forbidden_capture_kinds: list[str]
    global_scope_violation: Literal["REJECT_BUNDLE"]
    pair_scoped_evidence_reuse: Literal["CROSS_PAIR_CONTAMINATION"]
    global_scoped_evidence_reuse: Literal["DIAGNOSTIC_ONLY"]
    price_vector_overlap: Literal["DIAGNOSTIC_ONLY"]
    exact_s_acceptance_rule: Literal["R9_ENVELOPE_V1_VERIFIED_AND_SNAPSHOT_S_BOUND"]
    """EXACT_S only from ``verify_r9_envelope_v1(envelope, artifact_bytes).exact_s_accepted`` (policy 1.4.0)."""
    exact_s_identity_binding: Literal["EXACT_S_ID_EQ_SNAPSHOT_S_ID_AND_EXACT_S_SHA256_EQ_SNAPSHOT_S_SHA256"]
    r9_binding: Literal["R9_ENVELOPE_V1_VERIFIER_VERDICT_ONLY"]
    r9_envelope_status: Literal["FROZEN"]
    """Owner froze ``R9EnvelopeV1`` on 2026-09-28; the schema document is re-verified at load (fail closed)."""
    r9_envelope_schema_relpath: Literal["docs/governance/r9-envelope-v1.md"]
    r9_envelope_frozen_schema_sha256: str = Field(..., pattern=SHA256_PATTERN)
    r9_envelope_frozen_normative_span_sha256: str = Field(..., pattern=SHA256_PATTERN)
    shadow_acceptance_rule: Literal["GATE_PASSED_AND_EXACT_S_ACCEPTED_AND_R9_ENVELOPE_FROZEN"]
    required_broker_submit_count: Literal[0]
    operator_pair_selection_allowed: Literal[False]
    operator_direction_selection_allowed: Literal[False]
    no_candidate_status: Literal["WAIT"]

    @model_validator(mode="after")
    def _scope_kind_lists_pinned(self) -> HarnessPolicyV1:
        pinned = {
            "pair_binding_required_capture_kinds": (
                self.pair_binding_required_capture_kinds,
                PAIR_BINDING_REQUIRED_CAPTURE_KINDS,
            ),
            "global_scope_allowed_capture_kinds": (
                self.global_scope_allowed_capture_kinds,
                GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS,
            ),
            "global_scope_forbidden_capture_kinds": (
                self.global_scope_forbidden_capture_kinds,
                GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS,
            ),
        }
        drifted = sorted(name for name, (actual, expected) in pinned.items() if tuple(actual) != expected)
        if drifted:
            raise ValueError(f"evidence-scope kind lists must equal the enforced code lists: {', '.join(drifted)}")
        return self

    @model_validator(mode="after")
    def _r9_envelope_pin_is_the_owner_freeze(self) -> HarnessPolicyV1:
        pinned = {
            "r9_envelope_frozen_schema_sha256": (
                self.r9_envelope_frozen_schema_sha256,
                R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
            ),
            "r9_envelope_frozen_normative_span_sha256": (
                self.r9_envelope_frozen_normative_span_sha256,
                R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256,
            ),
        }
        drifted = sorted(name for name, (actual, expected) in pinned.items() if actual != expected)
        if drifted:
            raise ValueError(f"R9 envelope pin must equal the owner freeze record: {', '.join(drifted)}")
        return self


class LoadedPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: HarnessPolicyV1
    policy_sha256: str = Field(..., pattern=SHA256_PATTERN)


def load_policy_bytes(raw: bytes) -> LoadedPolicy:
    payload = parse_json_strict(raw)
    if not isinstance(payload, Mapping):
        raise HarnessInputError("POLICY_NOT_OBJECT", "policy must be a JSON object")
    try:
        policy = HarnessPolicyV1.model_validate(payload)
    except ValidationError as exc:
        raise HarnessInputError("POLICY_SCHEMA_INVALID", summarise_validation_error(exc)) from exc
    return LoadedPolicy(policy=policy, policy_sha256=sha256_hex(canonical_json_bytes(payload)))


def load_policy(path: Path) -> LoadedPolicy:
    return load_policy_bytes(_read(path, "POLICY_UNREADABLE"))


class SymbolBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    canonical_symbol: str = Field(..., pattern=CANONICAL_SYMBOL_PATTERN)
    broker_symbol: str = Field(..., pattern=BROKER_SYMBOL_PATTERN)


class SymbolUniverse(BaseModel):
    """Exactly ``expected_symbol_count`` unique canonical symbols, content-pinned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    universe_id: Literal["WOLF15_XM_30_V1"]
    source_relpath: str
    bindings: tuple[SymbolBinding, ...]
    canonical_sha256: str = Field(..., pattern=SHA256_PATTERN)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(binding.canonical_symbol for binding in self.bindings)

    def broker_symbol_for(self, canonical_symbol: str) -> str | None:
        for binding in self.bindings:
            if binding.canonical_symbol == canonical_symbol:
                return binding.broker_symbol
        return None


def universe_canonical_sha256(universe_id: str, bindings: tuple[SymbolBinding, ...]) -> str:
    """Hash of the ordered mapping, independent of CSV line endings or quoting."""

    content = {
        "universe": universe_id,
        "pairs": [[item.canonical_symbol, item.broker_symbol] for item in bindings],
    }
    return sha256_hex(canonical_json_bytes(content))


def load_symbol_universe_bytes(raw: bytes, loaded: LoadedPolicy) -> SymbolUniverse:
    policy = loaded.policy
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HarnessInputError("SYMBOL_MAP_NOT_UTF8", "symbol map is not UTF-8") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = [row for row in reader if row]
    if not rows or tuple(cell.strip() for cell in rows[0]) != _SYMBOL_MAP_HEADER:
        raise HarnessInputError("SYMBOL_MAP_HEADER_INVALID", "symbol map header must be canonical_symbol,broker_symbol")
    bindings: list[SymbolBinding] = []
    for index, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise HarnessInputError("SYMBOL_MAP_ROW_INVALID", f"row {index} must have exactly two cells")
        try:
            bindings.append(SymbolBinding(canonical_symbol=row[0].strip(), broker_symbol=row[1].strip()))
        except ValidationError as exc:
            raise HarnessInputError(
                "SYMBOL_MAP_ROW_INVALID", f"row {index}: {summarise_validation_error(exc)}"
            ) from exc
    frozen = tuple(bindings)
    if len(frozen) != policy.expected_symbol_count:
        raise HarnessInputError(
            "SYMBOL_COUNT_MISMATCH",
            f"symbol map has {len(frozen)} symbols, policy requires {policy.expected_symbol_count}",
        )
    if len({item.canonical_symbol for item in frozen}) != len(frozen):
        raise HarnessInputError("CANONICAL_SYMBOL_DUPLICATE", "canonical symbols are not unique")
    if len({item.broker_symbol for item in frozen}) != len(frozen):
        raise HarnessInputError("BROKER_SYMBOL_DUPLICATE", "broker symbols are not unique")
    digest = universe_canonical_sha256(policy.symbol_universe, frozen)
    if digest != policy.symbol_map_canonical_sha256:
        raise HarnessInputError(
            "SYMBOL_MAP_SHA_MISMATCH",
            f"symbol map canonical sha256 {digest} does not match the policy pin",
        )
    return SymbolUniverse(
        universe_id=policy.symbol_universe,
        source_relpath=policy.symbol_map_relpath,
        bindings=frozen,
        canonical_sha256=digest,
    )


def load_symbol_universe(path: Path, loaded: LoadedPolicy) -> SymbolUniverse:
    return load_symbol_universe_bytes(_read(path, "SYMBOL_MAP_UNREADABLE"), loaded)


def resolve_symbol_map_path(loaded: LoadedPolicy, repo_root: Path) -> Path:
    relpath = Path(loaded.policy.symbol_map_relpath)
    if relpath.is_absolute() or ".." in relpath.parts:
        raise HarnessInputError("SYMBOL_MAP_PATH_INVALID", "symbol_map_relpath must be repository-relative")
    return repo_root / relpath


class R9EnvelopePin(BaseModel):
    """The owner freeze of ``R9EnvelopeV1``, verified against the schema document at load.

    Only :func:`load_r9_envelope_pin_bytes` builds one after the document checks pass; the pinned hashes are
    re-checked here so a report cannot carry a different freeze.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_relpath: Literal["docs/governance/r9-envelope-v1.md"]
    envelope_status: Literal["FROZEN"]
    frozen_schema_sha256: str = Field(..., pattern=SHA256_PATTERN)
    frozen_normative_span_sha256: str = Field(..., pattern=SHA256_PATTERN)
    schema_document_sha256: str = Field(..., pattern=SHA256_PATTERN)
    """Observed sha256 of the (successor) schema document that carried the freeze record; recorded, not pinned."""

    @model_validator(mode="after")
    def _is_the_owner_freeze(self) -> R9EnvelopePin:
        if (self.frozen_schema_sha256, self.frozen_normative_span_sha256) != (
            R9_ENVELOPE_FROZEN_SCHEMA_SHA256,
            R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256,
        ):
            raise ValueError("R9 envelope pin must equal the owner freeze record")
        return self


def _freeze_record_line(key: str, value: str) -> str:
    return f"{key.ljust(_R9_FREEZE_RECORD_KEY_WIDTH)}= {value}"


def _freeze_record_holds(lines: list[str], key: str, value: str) -> bool:
    """Exactly one freeze-record line carries ``key`` and it is exactly ``key = value`` (column-aligned)."""

    carrying = [line for line in lines if line.startswith(key) and line[len(key) :].lstrip(" ").startswith("=")]
    return carrying == [_freeze_record_line(key, value)]


def load_r9_envelope_pin_bytes(raw: bytes, loaded: LoadedPolicy) -> R9EnvelopePin:
    """Verify the frozen R9 envelope schema document against the policy pin. Fail closed.

    * ``R9_ENVELOPE_NOT_FROZEN``: no single ``envelope_status = FROZEN`` freeze-record line, or ``NOT_FROZEN``
      appears anywhere in the document.
    * ``R9_ENVELOPE_PIN_MISMATCH``: the ``frozen_schema_sha256`` / ``frozen_normative_span_sha256`` /
      ``exact_s_final_authority`` / ``artifact_bytes`` lines differ from the pin, or the recomputed normative
      span sha256 differs from the pinned one.
    """

    policy = loaded.policy
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HarnessInputError("R9_ENVELOPE_PIN_MISMATCH", "R9 envelope schema document is not UTF-8") from exc
    lines = text.split("\n")
    if "NOT_FROZEN" in text or not _freeze_record_holds(lines, "envelope_status", policy.r9_envelope_status):
        raise HarnessInputError(
            "R9_ENVELOPE_NOT_FROZEN", "R9 envelope schema document does not carry envelope_status = FROZEN"
        )
    expected = {
        "frozen_schema_sha256": policy.r9_envelope_frozen_schema_sha256,
        "frozen_normative_span_sha256": policy.r9_envelope_frozen_normative_span_sha256,
        "exact_s_final_authority": "verify_r9_envelope_v1 verdict ONLY",
        "artifact_bytes": "REQUIRED",
    }
    drifted = sorted(key for key, value in expected.items() if not _freeze_record_holds(lines, key, value))
    start, end = raw.find(_R9_NORMATIVE_SPAN_START), raw.find(_R9_NORMATIVE_SPAN_END)
    span_ok = 0 <= start < end and sha256_hex(raw[start:end]) == policy.r9_envelope_frozen_normative_span_sha256
    if not span_ok:
        drifted.append("normative_span")
    if drifted:
        raise HarnessInputError(
            "R9_ENVELOPE_PIN_MISMATCH", f"R9 envelope schema document does not match the pin: {', '.join(drifted)}"
        )
    return R9EnvelopePin(
        schema_relpath=policy.r9_envelope_schema_relpath,
        envelope_status=policy.r9_envelope_status,
        frozen_schema_sha256=policy.r9_envelope_frozen_schema_sha256,
        frozen_normative_span_sha256=policy.r9_envelope_frozen_normative_span_sha256,
        schema_document_sha256=sha256_hex(raw),
    )


def load_r9_envelope_pin(loaded: LoadedPolicy, repo_root: Path) -> R9EnvelopePin:
    relpath = Path(loaded.policy.r9_envelope_schema_relpath)
    return load_r9_envelope_pin_bytes(_read(repo_root / relpath, "R9_ENVELOPE_SCHEMA_UNREADABLE"), loaded)


def _read(path: Path, code: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise HarnessInputError(code, f"cannot read {path.name}") from exc


def summarise_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


__all__ = [
    "CANONICAL_SYMBOL_PATTERN",
    "CAPTURE_KINDS",
    "GLOBAL_SCOPE_ALLOWED_CAPTURE_KINDS",
    "GLOBAL_SCOPE_FORBIDDEN_CAPTURE_KINDS",
    "PAIR_BINDING_REQUIRED_CAPTURE_KINDS",
    "R9_ENVELOPE_FROZEN_NORMATIVE_SPAN_SHA256",
    "R9_ENVELOPE_FROZEN_SCHEMA_SHA256",
    "R9_ENVELOPE_SCHEMA_RELPATH",
    "SHA256_PATTERN",
    "HarnessInputError",
    "HarnessPolicyV1",
    "LoadedPolicy",
    "R9EnvelopePin",
    "SymbolBinding",
    "SymbolUniverse",
    "canonical_json_bytes",
    "load_policy",
    "load_policy_bytes",
    "load_r9_envelope_pin",
    "load_r9_envelope_pin_bytes",
    "load_symbol_universe",
    "load_symbol_universe_bytes",
    "parse_json_strict",
    "resolve_symbol_map_path",
    "sha256_hex",
    "summarise_validation_error",
    "universe_canonical_sha256",
]
