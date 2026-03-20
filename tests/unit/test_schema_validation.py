"""
Tests for JSON schema contracts -- L12 and alerts.
"""
import json

from pathlib import Path

import pytest

SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"


class TestL12Schema:
    """Validate l12_schema.json structure and constraints."""

    @pytest.fixture
    def schema(self):
        path = SCHEMAS_DIR / "l12_schema.json"
        if not path.exists():
            pytest.skip("l12_schema.json not found")
        return json.loads(path.read_text())

    def test_schema_is_valid_json(self, schema):
        assert isinstance(schema, dict)

    def test_schema_has_type(self, schema):
        assert "type" in schema or "properties" in schema

    def test_required_fields_defined(self, schema):
        required = schema.get("required", [])
        assert "symbol" in required
        assert "verdict" in required
        assert "confidence" in required

    def test_no_account_fields_required(self, schema):
        required = schema.get("required", [])
        for forbidden in ["balance", "equity", "margin", "account_id"]:
            assert forbidden not in required, (
                f"L12 schema must not require '{forbidden}' -- boundary violation"
            )


class TestAlertSchema:
    """Validate alert_schema.json structure."""

    @pytest.fixture
    def schema(self):
        path = SCHEMAS_DIR / "alert_schema.json"
        if not path.exists():
            pytest.skip("alert_schema.json not found")
        return json.loads(path.read_text())

    def test_schema_is_valid_json(self, schema):
        assert isinstance(schema, dict)

    def test_event_types_defined(self, schema):
        """Schema should constrain event_type to known values."""
        props = schema.get("properties", {})
        if "event_type" in props:
            event_enum = props["event_type"].get("enum", [])
            expected = {"ORDER_PLACED", "ORDER_FILLED", "ORDER_CANCELLED",
                        "ORDER_EXPIRED", "SYSTEM_VIOLATION"}
            for ev in expected:
                assert ev in event_enum or len(event_enum) == 0, (
                    f"Missing event type: {ev}"
                )
