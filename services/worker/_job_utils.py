"""Shared helpers for Wolf-15 cron worker jobs.

These helpers keep worker jobs deterministic and side-effect scoped to
analysis artifacts (Redis/file), with no execution authority.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from loguru import logger

from storage.redis_client import RedisClient


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json_from_file(path_str: str) -> Any:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"json source file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_redis_client() -> RedisClient:
    return RedisClient()


def load_json_payload(
    *,
    env_json_var: str,
    env_file_var: str,
    redis_key: str,
) -> Any:
    """Load JSON payload from env-inline, env-file, or Redis key (priority order)."""
    inline = (os.getenv(env_json_var) or "").strip()
    if inline:
        return json.loads(inline)

    file_path = (os.getenv(env_file_var) or "").strip()
    if file_path:
        return _load_json_from_file(file_path)

    raw = (get_redis_client().get(redis_key) or "").strip()
    if raw:
        return json.loads(raw)

    return None


def normalize_returns(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []

    normalized: list[float] = []
    for item in cast(list[Any], values):
        fv = _safe_float(item)
        if fv is not None:
            normalized.append(fv)
    return normalized


def normalize_return_matrix(values: Any) -> dict[str, list[float]]:
    if not isinstance(values, dict):
        return {}

    matrix: dict[str, list[float]] = {}
    for key, raw_returns in cast(dict[Any, Any], values).items():
        label = str(key).strip().upper()
        if not label:
            continue
        returns = normalize_returns(raw_returns)
        if returns:
            matrix[label] = returns
    return matrix


def write_json_artifact(relative_path: str, payload: dict[str, Any]) -> Path:
    out_path = Path(relative_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def publish_result(redis_key: str, payload: dict[str, Any]) -> None:
    try:
        get_redis_client().set(redis_key, json.dumps(payload))
    except Exception as exc:  # pragma: no cover - logging side path
        logger.warning("failed to publish {} to redis: {}", redis_key, exc)
