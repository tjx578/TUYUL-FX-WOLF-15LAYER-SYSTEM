"""Tests for services.orchestrator.redis_commands."""

from __future__ import annotations

import json

import pytest

from services.orchestrator.redis_commands import CommandParseError, parse_set_mode_command


class TestParseSetModeCommand:
    def test_valid_set_mode_command(self) -> None:
        raw = json.dumps({"command": "set_mode", "mode": "NORMAL", "reason": "manual"})
        result = parse_set_mode_command(raw)
        assert result.mode == "NORMAL"
        assert result.reason == "manual"

    def test_valid_mode_set_command(self) -> None:
        raw = json.dumps({"command": "mode_set", "mode": "PAUSED"})
        result = parse_set_mode_command(raw)
        assert result.mode == "PAUSED"
        assert result.reason == "command"

    def test_event_field_does_not_trigger_mode_change(self) -> None:
        """event field must NOT be treated as a command — prevents telemetry crosstalk."""
        raw = json.dumps({"event": "set_mode", "mode": "NORMAL"})
        with pytest.raises(CommandParseError, match="Unsupported command"):
            parse_set_mode_command(raw)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(CommandParseError, match="Invalid JSON"):
            parse_set_mode_command("not-json")

    def test_unsupported_command_raises(self) -> None:
        raw = json.dumps({"command": "shutdown", "mode": "NORMAL"})
        with pytest.raises(CommandParseError, match="Unsupported command"):
            parse_set_mode_command(raw)

    def test_missing_mode_raises(self) -> None:
        raw = json.dumps({"command": "set_mode"})
        with pytest.raises(CommandParseError, match="Missing mode"):
            parse_set_mode_command(raw)

    def test_missing_command_field_raises(self) -> None:
        raw = json.dumps({"mode": "NORMAL"})
        with pytest.raises(CommandParseError, match="Unsupported command"):
            parse_set_mode_command(raw)
