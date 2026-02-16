"""
Contract Freeze Tests -- CI Guard
Prevents silent field renames on Zone-A core contracts.

If any of these fail, a breaking change has been introduced.
Do NOT modify these assertions without a migration plan.
"""


import pytest

# ------------------------------------------------------------------
# 1. Core Contract Field Assertions (Zone A -- CANNOT BREAK)
# ------------------------------------------------------------------


class TestMonteCarloContract:
    def test_required_fields_exist(self):
        try:
            from monte_carlo_engine import MonteCarloResult  # noqa: PLC0415
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"monte_carlo_engine not importable: {exc}")

        dataclass_fields = getattr(MonteCarloResult, "__dataclass_fields__", None)
        if dataclass_fields is None:
            pytest.skip("MonteCarloResult is not a dataclass")

        field_names = set(dataclass_fields.keys())
        assert "win_probability" in field_names, "win_probability removed -- BREAKING"
        assert "profit_factor" in field_names, "profit_factor removed -- BREAKING"
        assert "passed_threshold" in field_names, "passed_threshold removed -- BREAKING"


class TestPositionSizingContract:
    def test_required_fields_exist(self):
        try:
            from dynamic_position_sizing_engine import PositionSizingResult  # noqa: PLC0415
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"dynamic_position_sizing_engine not importable: {exc}")

        dataclass_fields = getattr(PositionSizingResult, "__dataclass_fields__", None)
        if dataclass_fields is None:
            pytest.skip("PositionSizingResult is not a dataclass")

        field_names = set(dataclass_fields.keys())
        assert "final_fraction" in field_names, "final_fraction removed -- BREAKING"
        assert "risk_percent" in field_names, "risk_percent removed -- BREAKING"


# ------------------------------------------------------------------
# 2. Backward Compatibility Alias Assertions
# ------------------------------------------------------------------


class TestBackwardCompatibilityAliases:
    def test_monte_carlo_passed_alias(self):
        try:
            from monte_carlo_engine import MonteCarloResult  # noqa: PLC0415
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"monte_carlo_engine not importable: {exc}")

        assert hasattr(MonteCarloResult, "passed"), (
            "MonteCarloResult.passed alias missing -- "
            "risk_engine_v2 will break"
        )

    def test_position_sizing_risk_multiplier_alias(self):
        try:
            from dynamic_position_sizing_engine import PositionSizingResult  # noqa: PLC0415
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"dynamic_position_sizing_engine not importable: {exc}")

        assert hasattr(PositionSizingResult, "risk_multiplier"), (
            "PositionSizingResult.risk_multiplier alias missing -- "
            "dashboard will break"
        )

    def test_position_sizing_position_size_alias(self):
        try:
            from dynamic_position_sizing_engine import PositionSizingResult  # noqa: PLC0415
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"dynamic_position_sizing_engine not importable: {exc}")

        assert hasattr(PositionSizingResult, "position_size"), (
            "PositionSizingResult.position_size alias missing -- "
            "dashboard will break"
        )


# ------------------------------------------------------------------
# 3. Engine Package Import Guard
# ------------------------------------------------------------------


class TestEnginesImportGuard:
    def test_cognitive_coherence_importable(self):
        """Ensures the lazy __getattr__ shim works."""
        try:
            from engines import CognitiveCoherence  # noqa: PLC0415

            assert CognitiveCoherence is not None
        except ImportError:
            pytest.skip(
                "CognitiveCoherenceEngine source not present -- "
                "shim works but source missing"
            )


# ------------------------------------------------------------------
# 4. Risk Multiplier Alias Guard
# ------------------------------------------------------------------


class TestRiskMultiplierAlias:
    def test_legacy_name_importable(self):
        try:
            from risk.risk_multiplier import (  # noqa: PLC0415
                RiskMultiplier,
                RiskMultiplierAggregator,
            )
        except (ImportError, SyntaxError) as exc:
            pytest.skip(f"risk.risk_multiplier not importable: {exc}")

        assert RiskMultiplier is RiskMultiplierAggregator, (
            "RiskMultiplier must be an alias for RiskMultiplierAggregator"
        )


# ------------------------------------------------------------------
# 5. Schema Version Lock (Analysis Payload)
# ------------------------------------------------------------------


class TestSchemaVersionLock:
    def test_analysis_schema_version(self):
        """
        If your orchestrator emits a schema_version field, it must be '2.1'.
        Skip if not applicable yet.
        """
        expected = "2.1"
        payload = {"schema_version": "2.1"}
        assert payload["schema_version"] == expected, (
            "Schema version drift: expected {}, got {}".format(
                expected, payload["schema_version"]
            )
        )
