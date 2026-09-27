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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CANONICAL_SYMBOL_PATTERN: Final = r"^[A-Z]{6}$"
BROKER_SYMBOL_PATTERN: Final = r"^[A-Za-z0-9._#-]{1,32}$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_SYMBOL_MAP_HEADER: Final = ("canonical_symbol", "broker_symbol")


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
    pair_scoped_evidence_reuse: Literal["CROSS_PAIR_CONTAMINATION"]
    global_scoped_evidence_reuse: Literal["DIAGNOSTIC_ONLY"]
    price_vector_overlap: Literal["DIAGNOSTIC_ONLY"]
    exact_s_acceptance_rule: Literal["R9_ARTIFACT_BOUND"]
    r9_binding: Literal["R9_ARTIFACT_SHA256_MATCH_ONLY"]
    r9_envelope_status: Literal["NOT_FROZEN"]
    """The frozen R9 artifact envelope does not exist yet; no other value is admissible until its schema is frozen."""
    shadow_acceptance_rule: Literal["GATE_PASSED_AND_EXACT_S_ACCEPTED_AND_R9_ENVELOPE_FROZEN"]
    required_broker_submit_count: Literal[0]
    operator_pair_selection_allowed: Literal[False]
    operator_direction_selection_allowed: Literal[False]
    no_candidate_status: Literal["WAIT"]


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
    "SHA256_PATTERN",
    "HarnessInputError",
    "HarnessPolicyV1",
    "LoadedPolicy",
    "SymbolBinding",
    "SymbolUniverse",
    "canonical_json_bytes",
    "load_policy",
    "load_policy_bytes",
    "load_symbol_universe",
    "load_symbol_universe_bytes",
    "parse_json_strict",
    "resolve_symbol_map_path",
    "sha256_hex",
    "summarise_validation_error",
    "universe_canonical_sha256",
]
