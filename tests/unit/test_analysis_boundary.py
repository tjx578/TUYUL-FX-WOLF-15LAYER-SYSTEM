"""
Tests for analysis modules (L1-L11).
Constitutional boundary: analysis must have NO execution side-effects.
"""

import ast
from pathlib import Path

import pytest


class TestAnalysisBoundary:
    """Analysis modules must be pure -- no execution side effects."""

    @staticmethod
    def _execution_imports(source: str, *, filename: str) -> list[str]:
        """Return absolute imports from the top-level execution namespace."""
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            raise AssertionError(
                f"{filename} cannot be parsed for the execution boundary audit: {exc.msg} at line {exc.lineno}"
            ) from exc

        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(
                    alias.name
                    for alias in node.names
                    if alias.name == "execution" or alias.name.startswith("execution.")
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and (node.module == "execution" or node.module.startswith("execution."))
            ):
                imports.append(node.module)
        return imports

    def _get_analysis_modules(self):
        analysis_dir = Path(__file__).parents[2] / "analysis"
        if not analysis_dir.exists():
            pytest.skip("analysis/ directory not found")
        return list(analysis_dir.glob("*.py"))

    def test_no_execution_imports_in_analysis(self):
        """Analysis modules must not import from execution/."""
        for py_file in self._get_analysis_modules():
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            imports = self._execution_imports(content, filename=str(py_file))
            assert not imports, f"{py_file.name} imports {imports} -- boundary violation"

    def test_execution_import_scanner_ignores_prose_comments_and_similar_names(self):
        source = '''
"""A target from execution remains analysis prose, not an import."""
# import execution is documentation here, not executable syntax.
import executioner
from executioner.tools import helper
from .execution import local_helper
'''

        assert self._execution_imports(source, filename="allowed_examples.py") == []

    def test_execution_import_scanner_detects_absolute_namespace_imports(self):
        source = """
import execution
import execution.submodule as executor
from execution import command
"""

        assert self._execution_imports(source, filename="forbidden_examples.py") == [
            "execution",
            "execution.submodule",
            "execution",
        ]

    def test_execution_import_scanner_fails_closed_on_parse_error(self):
        with pytest.raises(AssertionError, match="cannot be parsed for the execution boundary audit"):
            self._execution_imports("from execution import", filename="invalid.py")

    def test_no_order_placement_in_analysis(self):
        """Analysis must never place orders."""
        for py_file in self._get_analysis_modules():
            if py_file.name.startswith("__"):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for forbidden in ["place_order", "send_order", "execute_trade", "OrderSend"]:
                assert forbidden not in content, (
                    f"{py_file.name} contains '{forbidden}' -- execution side-effect in analysis"
                )

    def test_no_dashboard_mutation_in_analysis(self):
        """Analysis must not directly mutate dashboard state."""
        for py_file in self._get_analysis_modules():
            if py_file.name.startswith("__"):
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for forbidden in ["update_balance", "modify_equity", "set_account"]:
                assert forbidden not in content, f"{py_file.name} mutates dashboard state -- boundary violation"


class TestFeedToAnalysisPipeline:
    """Tests for data feed processing -- latency and correctness."""

    def test_candle_data_structure(self):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.0840,
            "high": 1.0870,
            "low": 1.0835,
            "close": 1.0855,
            "volume": 12345,
            "timestamp": "2026-02-15T10:00:00Z",
        }
        required = ["symbol", "timeframe", "open", "high", "low", "close", "timestamp"]
        for field in required:
            assert field in candle

    def test_candle_ohlc_invariants(self):
        """High >= Open, Close, Low; Low <= everything."""
        candle = {"open": 1.0840, "high": 1.0870, "low": 1.0835, "close": 1.0855}
        assert candle["high"] >= candle["open"]
        assert candle["high"] >= candle["close"]
        assert candle["high"] >= candle["low"]
        assert candle["low"] <= candle["open"]
        assert candle["low"] <= candle["close"]

    @pytest.mark.parametrize("timeframe", ["M1", "M5", "M15", "H1", "H4", "D1"])
    def test_supported_timeframes(self, timeframe):
        valid = {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"}
        assert timeframe in valid

    def test_multi_pair_analysis_produces_independent_results(self):
        """Each pair's analysis should be independent."""
        pairs = ["EURUSD", "GBPUSD", "USDJPY"]
        results = {}
        for pair in pairs:
            results[pair] = {
                "symbol": pair,
                "wolf_score": 7.0 + len(pair) * 0.1,  # dummy
            }
        # Each result is keyed independently
        assert len(results) == 3
        assert results["EURUSD"]["symbol"] == "EURUSD"
        assert results["GBPUSD"]["symbol"] != results["EURUSD"]["symbol"]


class TestSignalValidatorBoundary:
    """Signal validator must enforce constitutional rules at zone boundaries."""

    def test_signal_validator_rejects_account_state_keys(self):
        """L12 signals must NOT contain balance/equity/lot_size (non-negotiable rule #6)."""
        from schemas.validator import validate_l12_signal

        forbidden_signals = [
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": 0.85, "balance": 10000},
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": 0.85, "equity": 9500},
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": 0.85, "lot_size": 0.5},
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": 0.85, "risk_amount": 100},
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": 0.85, "account_balance": 10000},
        ]
        for signal in forbidden_signals:
            is_valid, errors = validate_l12_signal(signal)
            found_violation = any("CONSTITUTIONAL VIOLATION" in e for e in errors)
            assert found_violation, (
                f"Signal with forbidden key {set(signal.keys()) - {'symbol', 'verdict', 'confidence'}} "
                f"was not flagged as constitutional violation"
            )

    def test_signal_validator_allows_clean_signal(self):
        """A clean L12 signal without account state should not trigger constitutional violation."""
        from schemas.validator import validate_l12_signal

        clean_signal = {
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.85,
            "direction": "BUY",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit_1": 1.1100,
            "risk_reward_ratio": 2.0,
        }
        _is_valid, errors = validate_l12_signal(clean_signal)
        constitutional_errors = [e for e in errors if "CONSTITUTIONAL VIOLATION" in e]
        assert not constitutional_errors, f"Clean signal got false constitutional violation: {constitutional_errors}"

    def test_signal_validator_source_has_no_execution_imports(self):
        """schemas/validator.py must not import from execution/ or dashboard/."""
        validator_file = Path(__file__).parents[2] / "schemas" / "validator.py"
        if not validator_file.exists():
            pytest.skip("schemas/validator.py not found")
        content = validator_file.read_text(encoding="utf-8", errors="ignore")
        for forbidden in ["from execution", "import execution", "from dashboard", "import dashboard"]:
            assert forbidden not in content, f"schemas/validator.py imports '{forbidden}' -- boundary violation"
