"""Portable replay inputs for an explicitly supplied confidential evidence sink.

This codec provides neither encryption nor reader attestation. The caller owns
storage access controls and independently retains the expected receipt digest.
No filesystem, environment configuration, or broker access is used here.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

SCHEMA = "wolf15.channel-b-replay-bundle.v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 64


def _pack(value: Any, depth: int = 0) -> list[Any]:
    if depth > MAX_DEPTH:
        raise ValueError("REPLAY_BUNDLE_TOO_DEEP")
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("REPLAY_BUNDLE_NONSTRING_KEY")
        return ["dict", [[key, _pack(item, depth + 1)] for key, item in sorted(value.items())]]
    if type(value) is list:
        return ["list", [_pack(item, depth + 1) for item in value]]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("REPLAY_BUNDLE_NAIVE_TIME")
        return ["datetime", value.isoformat()]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("REPLAY_BUNDLE_NONFINITE_DECIMAL")
        return ["decimal", str(value)]
    if isinstance(value, UUID):
        return ["uuid", str(value)]
    if value is None or type(value) in (bool, int, float, str):
        return ["value", value]
    raise ValueError("REPLAY_BUNDLE_UNSUPPORTED_TYPE")


def _unpack(node: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH or type(node) is not list or len(node) != 2:
        raise ValueError("MALFORMED_REPLAY_BUNDLE")
    tag, value = node
    if tag == "dict" and type(value) is list:
        result = {}
        for pair in value:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or pair[0] in result:
                raise ValueError("MALFORMED_REPLAY_BUNDLE")
            result[pair[0]] = _unpack(pair[1], depth + 1)
        return result
    if tag == "list" and type(value) is list:
        return [_unpack(item, depth + 1) for item in value]
    if type(value) is str:
        if tag == "datetime":
            return datetime.fromisoformat(value)
        if tag == "decimal":
            return Decimal(value)
        if tag == "uuid":
            return UUID(value)
    if tag == "value" and (value is None or type(value) in (bool, int, float, str)):
        return value
    raise ValueError("MALFORMED_REPLAY_BUNDLE")


def encode_replay_bundle(*, report: dict, database: dict, broker: dict) -> bytes:
    payload = [SCHEMA, _pack({"report": report, "database": database, "broker": broker})]
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    if len(encoded) > MAX_BYTES:
        raise ValueError("REPLAY_BUNDLE_TOO_LARGE")
    return encoded


def decode_replay_bundle(encoded: bytes) -> dict[str, Any]:
    """Load data only; no dynamic imports, pickle, or type-selected execution."""
    if type(encoded) is not bytes or len(encoded) > MAX_BYTES:
        raise ValueError("INVALID_REPLAY_BUNDLE_SIZE_OR_TYPE")
    try:
        payload = json.loads(encoded)
        if type(payload) is not list or len(payload) != 2 or payload[0] != SCHEMA:
            raise ValueError("MALFORMED_REPLAY_BUNDLE")
        bundle = _unpack(payload[1])
        if type(bundle) is not dict or set(bundle) != {"report", "database", "broker"}:
            raise ValueError("MALFORMED_REPLAY_BUNDLE")
        if any(type(item) is not dict for item in bundle.values()):
            raise ValueError("MALFORMED_REPLAY_BUNDLE")
        # Require the one canonical encoding, rejecting duplicate keys, exotic
        # scalars, naive dates, nonfinite numbers and ambiguous typed lookalikes.
        if encode_replay_bundle(**bundle) != encoded:
            raise ValueError("NONCANONICAL_REPLAY_BUNDLE")
        return bundle
    except (ValueError, TypeError, ArithmeticError, RecursionError, UnicodeError) as exc:
        raise ValueError("MALFORMED_REPLAY_BUNDLE") from exc
