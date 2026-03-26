"""Parsing helpers for orchestrator Redis command payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CommandParseError(ValueError):
    """Raised when a Redis command payload is invalid."""


class RedisCommandName(StrEnum):
    SET_MODE = "set_mode"
    MODE_SET = "mode_set"


@dataclass(frozen=True, slots=True)
class SetModeCommand:
    mode: str
    reason: str


def _as_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def parse_set_mode_command(raw_message: str) -> SetModeCommand:
    try:
        payload = _as_dict(json.loads(raw_message))
    except json.JSONDecodeError as exc:
        raise CommandParseError("Invalid JSON payload for set_mode") from exc

    command = str(payload.get("command") or payload.get("event") or "").strip().lower()
    if command not in {RedisCommandName.SET_MODE.value, RedisCommandName.MODE_SET.value}:
        raise CommandParseError(f"Unsupported command: {command!r}")

    raw_mode = str(payload.get("mode", "")).strip().upper()
    if not raw_mode:
        raise CommandParseError("Missing mode in set_mode command")

    reason = str(payload.get("reason") or "command").strip() or "command"
    return SetModeCommand(mode=raw_mode, reason=reason)
