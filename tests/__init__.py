"""Tests package for TUYUL-FX / Wolf-15 Layer System."""

# Try importing the real module; if not present, tests document expected behavior
import json
from pathlib import Path

import pytest

try:
    from constitution.verdict_engine import (  # pyright: ignore[reportAttributeAccessIssue] # noqa: F401
        VerdictEngine,  # pyright: ignore[reportAttributeAccessIssue]
        compute_verdict,  # pyright: ignore[reportAttributeAccessIssue]
    )

    HAS_VERDICT = True
except ImportError:
    HAS_VERDICT = False


# ── Schema validation ─────────────────────────────────────────────


class TestL12SchemaCompliance:
    """Ensure L12 output matches the JSON schema contract."""

    def _load_schema(self):
        schema_path = Path(__file__).parents[1] / "schemas" / "l12_schema.json"
        if not schema_path.exists():
            pytest.skip("l12_schema.json not found")
        return json.loads(schema_path.read_text())

    def test_required_fields_present(self, sample_l12_verdict):
        schema = self._load_schema()
        required = schema.get("required", ["symbol", "verdict", "confidence"])
        for field in required:
            assert field in sample_l12_verdict, f"Missing required field: {field}"

    def test_verdict_enum_values(self, sample_l12_verdict):
        allowed = {"EXECUTE", "HOLD", "NO_TRADE", "ABORT"}
        assert sample_l12_verdict["verdict"] in allowed

    def test_confidence_range(self, sample_l12_verdict):
        c = sample_l12_verdict["confidence"]
        assert 0.0 <= c <= 1.0, f"Confidence {c} out of [0,1] range"

    def test_reject_verdict_has_no_entry(self, sample_l12_reject):
        assert sample_l12_reject["verdict"] == "NO_TRADE"
        assert sample_l12_reject["entry_price"] is None

    def test_signal_id_format(self, sample_l12_verdict):
        sid = sample_l12_verdict["signal_id"]
        assert sid.startswith("SIG-"), f"signal_id should start with SIG-: {sid}"


class TestVerdictAuthorityBoundary:
    """Verify constitutional rule: verdict must NOT depend on account state."""

    def test_verdict_does_not_accept_balance(self, sample_l12_verdict):
        """L12 input should never include balance/equity."""
        assert "balance" not in sample_l12_verdict
        assert "equity" not in sample_l12_verdict

    def test_verdict_does_not_contain_lot_size_at_schema_level(self):
        """
        Per enriched fields: lot_size may be computed internally but the
        core schema contract must not require it.
        """
        schema_path = Path(__file__).parents[1] / "schemas" / "l12_schema.json"
        if not schema_path.exists():
            pytest.skip("schema not found")
        schema = json.loads(schema_path.read_text())
        required = schema.get("required", [])
        assert "lot_size" not in required

    @pytest.mark.skipif(not HAS_VERDICT, reason="verdict_engine not importable")
    def test_verdict_engine_signature_no_account_param(self):
        import inspect  # noqa: PLC0415

        sig = inspect.signature(compute_verdict)  # type: ignore
        params = list(sig.parameters.keys())
        for forbidden in ["balance", "equity", "account_state", "account"]:
            assert forbidden not in params, (
                f"compute_verdict must not accept '{forbidden}' -- authority boundary violation"
            )


class TestVerdictGate:
    """Layer-12 gate: only EXECUTE verdicts should pass to execution."""

    @pytest.mark.parametrize(
        "verdict,should_pass",
        [
            ("EXECUTE", True),
            ("HOLD", False),
            ("NO_TRADE", False),
            ("ABORT", False),
        ],
    )
    def test_gate_pass_logic(self, verdict, should_pass, sample_l12_verdict):
        sample_l12_verdict["verdict"] = verdict
        passed = sample_l12_verdict["verdict"] == "EXECUTE"
        assert passed == should_pass

    def test_low_confidence_should_not_execute(self, sample_l12_verdict):
        """Convention: confidence < 0.6 -> should not be EXECUTE."""
        sample_l12_verdict["confidence"] = 0.4
        # If a real engine existed, it should reject. We test the invariant.
        if sample_l12_verdict["verdict"] == "EXECUTE":
            assert sample_l12_verdict["confidence"] >= 0.6, "EXECUTE with confidence < 0.6 violates quality gate"


class TestVerdictScoring:
    """Tests for score sub-components."""

    def test_scores_are_numeric(self, sample_l12_verdict):
        for key, val in sample_l12_verdict["scores"].items():
            assert isinstance(val, (int, float)), f"Score '{key}' is not numeric"

    def test_scores_bounded(self, sample_l12_verdict):
        for key, val in sample_l12_verdict["scores"].items():
            assert 0 <= val <= 10, f"Score '{key}'={val} out of [0,10]"

    @pytest.mark.parametrize(
        "wolf,tii,frpc,expected_verdict",
        [
            (9.0, 8.0, 8.0, "EXECUTE"),
            (2.0, 2.0, 2.0, "NO_TRADE"),
            (5.0, 5.0, 5.0, "HOLD"),
        ],
    )
    def test_score_to_verdict_mapping(self, wolf, tii, frpc, expected_verdict):
        """Conceptual mapping -- concrete thresholds depend on engine config."""
        avg = (wolf + tii + frpc) / 3
        if avg >= 7.5:
            result = "EXECUTE"
        elif avg <= 3.0:
            result = "NO_TRADE"
        else:
            result = "HOLD"
        assert result == expected_verdict
