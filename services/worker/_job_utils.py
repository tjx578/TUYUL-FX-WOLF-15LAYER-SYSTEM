"""Shared helpers for Wolf-15 cron worker jobs.

These helpers keep worker jobs deterministic and side-effect scoped to
analysis artifacts (Redis/file), with no execution authority.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from json import JSONDecodeError
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


_redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    global _redis_client  # noqa: PLW0603
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


def _looks_like_placeholder_json(raw: str) -> bool:
    normalized = raw.strip().lower()
    return normalized in {
        "json string",
        "(json string)",
        "<json string>",
        "your_json_here",
        "<your_json_here>",
    }


def _load_json_string(raw: str, *, source: str) -> Any:
    try:
        return json.loads(raw)
    except JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc


def load_json_payload(
    *,
    env_json_var: str,
    env_file_var: str,
    redis_key: str,
) -> Any:
    """Load JSON payload from env-inline, env-file, or Redis key (priority order)."""
    inline = (os.getenv(env_json_var) or "").strip()
    if inline:
        if _looks_like_placeholder_json(inline):
            logger.warning(
                "{} is set to a placeholder value; ignoring inline JSON and checking fallback sources",
                env_json_var,
            )
        else:
            try:
                return _load_json_string(inline, source=f"env var {env_json_var}")
            except ValueError as exc:
                logger.warning("{}", exc)
                logger.warning(
                    "Ignoring invalid inline JSON from {} and checking fallback sources",
                    env_json_var,
                )

    file_path = (os.getenv(env_file_var) or "").strip()
    if file_path:
        return _load_json_from_file(file_path)

    raw = (get_redis_client().get(redis_key) or "").strip()
    if raw:
        return _load_json_string(raw, source=f"Redis key {redis_key}")

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


def _artifact_redis_key(relative_path: str) -> str:
    """Deterministic Redis key for a filesystem artifact path."""
    return f"WOLF15:ARTIFACT:{relative_path}"


def write_json_artifact(relative_path: str, payload: dict[str, Any]) -> Path:
    """Persist artifact to Redis (primary) and filesystem (best-effort).

    On ephemeral-filesystem deployments (Railway) the filesystem copy may be
    lost on restart, so Redis is the durable store.
    """
    serialised = json.dumps(payload, indent=2)

    # Primary: Redis
    try:
        get_redis_client().set(_artifact_redis_key(relative_path), serialised)
    except Exception as exc:  # pragma: no cover
        logger.warning("failed to persist artifact {} to redis: {}", relative_path, exc)

    # Best-effort: filesystem
    out_path = Path(relative_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialised, encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        logger.warning("failed to write artifact to filesystem {}: {}", relative_path, exc)

    return out_path


def read_json_artifact(relative_path: str) -> dict[str, Any] | None:
    """Read artifact from Redis first, filesystem fallback.

    Returns ``None`` when the artifact cannot be found in either store.
    """
    redis_key = _artifact_redis_key(relative_path)
    try:
        raw = (get_redis_client().get(redis_key) or "").strip()
        if raw:
            return json.loads(raw)
    except Exception as exc:  # pragma: no cover
        logger.warning("failed to read artifact {} from redis: {}", relative_path, exc)

    # Fallback: filesystem
    fs_path = Path(relative_path)
    if fs_path.exists():
        try:
            return json.loads(fs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
            logger.warning("failed to read artifact from filesystem {}: {}", relative_path, exc)

    return None


def publish_result(redis_key: str, payload: dict[str, Any]) -> None:
    try:
        get_redis_client().set(redis_key, json.dumps(payload))
    except Exception as exc:  # pragma: no cover - logging side path
        logger.warning("failed to publish {} to redis: {}", redis_key, exc)
