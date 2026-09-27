"""Neutral V31 identity helpers: ONE implementation of encoding, canonical serialization and hashing.

Owner decision (2026-09-20, #493 replacement): the S1B lineage (#501–#503) and the analysis-admission receipt share
these helpers instead of local copies. This module holds no authority semantics and derives no lifecycle or
admission identity by itself; each authority object keeps its own namespace and tuple.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID, uuid5

IDENTITY_ENCODING_VERSION = "v31.native-identity.v1"
# SSOT v3.1 candidate bytes, pinned byte-exact (docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md).
SELECTED_SSOT_HASH = "sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"

IdentityPart = str | int | None


def canonical_json_v31(value: object) -> str:
    """Canonical JSON used by every V31 hash: sorted keys, no whitespace, no NaN/Infinity."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256_v31(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_v31(value).encode("utf-8")).hexdigest()


def identity_name_v31(parts: Sequence[IdentityPart]) -> str:
    """UUIDv5 name: a JSON array [encoding version, *parts]. No string concatenation, no field ambiguity."""

    return json.dumps([IDENTITY_ENCODING_VERSION, *parts], separators=(",", ":"))


def identity_uuid_v31(namespace: UUID, parts: Sequence[IdentityPart]) -> UUID:
    return uuid5(namespace, identity_name_v31(parts))


__all__ = [
    "IDENTITY_ENCODING_VERSION",
    "SELECTED_SSOT_HASH",
    "IdentityPart",
    "canonical_json_v31",
    "canonical_sha256_v31",
    "identity_name_v31",
    "identity_uuid_v31",
]
