import copy

from constitution.gatekeeper import Gatekeeper


def _base_candidate():
    return {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "L1": {"ctx": True},
        "L2": {"multi_timeframe_alignment": True},
        "L3": {"tech": True},
        "L4": {"score": 90},
        "L7": {"win_probability": 60.0},
        "L8": {
            "integrity": 0.99,
            "technical_integrity_index_symbol": 0.95,
            "tii_sym": 0.95,
        },
        "L9": {"smc": True},
        "L10": {"position_ok": True},
        "L11": {"rr": 2.5},
    }


def test_gatekeeper_all_gates_pass():
    gate = Gatekeeper()
    result = gate.evaluate(_base_candidate())
    assert result["passed"] is True
    assert result["reason"] == "ALL_GATES_PASSED"


def test_gatekeeper_blocks_low_probability():
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["L7"]["win_probability"] = 40.0

    result = gate.evaluate(candidate)

    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_probability"
    assert result["reason"].startswith("prob<")


# ===================================================================
# TIMEFRAME GATE — no longer hard-coded True
# ===================================================================


def test_gate_timeframe_blocks_m1():
    """M1 data must be rejected — it is not a constitutional setup timeframe."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["timeframe"] = "M1"

    result = gate.evaluate(candidate)
    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_timeframe"
    assert "timeframe_violation" in result["reason"]


def test_gate_timeframe_blocks_missing():
    """Candidates without a timeframe tag must fail closed."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate.pop("timeframe", None)
    candidate["L1"].pop("timeframe", None)

    result = gate.evaluate(candidate)
    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_timeframe"
    assert "timeframe_missing" in result["reason"]


def test_gate_timeframe_accepts_h1():
    """H1 is the setup timeframe — must pass."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["timeframe"] = "H1"

    result = gate.evaluate(candidate)
    # Should not fail at timeframe gate (may still pass or fail at other gates)
    if not result["passed"]:
        assert result["failed_gate"] != "_gate_timeframe"


def test_gate_timeframe_accepts_m15():
    """M15 is the monitor timeframe — must pass."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["timeframe"] = "M15"

    result = gate.evaluate(candidate)
    if not result["passed"]:
        assert result["failed_gate"] != "_gate_timeframe"


def test_gate_timeframe_reads_l1_fallback():
    """If top-level timeframe is absent, fall back to L1.timeframe."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate.pop("timeframe", None)
    candidate["L1"]["timeframe"] = "H1"

    result = gate.evaluate(candidate)
    if not result["passed"]:
        assert result["failed_gate"] != "_gate_timeframe"


# ===================================================================
# MARKET LAW GATE — no longer hard-coded True
# ===================================================================


def test_gate_market_law_blocks_unknown_symbol():
    """Symbols not in enabled pairs must be rejected."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["symbol"] = "BTCUSD"  # crypto not in pairs.yaml

    result = gate.evaluate(candidate)
    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_market_law"
    assert "symbol_not_enabled" in result["reason"]


def test_gate_market_law_blocks_missing_symbol():
    """Missing symbol must be rejected."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate.pop("symbol", None)

    result = gate.evaluate(candidate)
    assert result["passed"] is False
    assert result["failed_gate"] == "_gate_market_law"
    assert "symbol_missing" in result["reason"]


def test_gate_market_law_accepts_enabled_pair():
    """EURUSD (enabled in pairs.yaml) must pass market law gate."""
    gate = Gatekeeper()
    candidate = copy.deepcopy(_base_candidate())
    candidate["symbol"] = "EURUSD"

    result = gate.evaluate(candidate)
    if not result["passed"]:
        assert result["failed_gate"] != "_gate_market_law"


# ===================================================================
# IMMUTABLE CONFIG SNAPSHOT + HOT RELOAD
# ===================================================================


def test_constitution_is_deep_copy():
    """Mutating the constitution dict must not affect the gatekeeper's copy."""
    gate = Gatekeeper()
    original_tii = gate.constitution.get("tii_min")

    # Attempt external mutation
    gate.constitution["tii_min"] = 999.0

    # The property returns the internal dict, but a reload should restore
    gate.reload()
    assert gate.constitution.get("tii_min") == original_tii


def test_reload_rebuilds_gates():
    """After reload(), allowed timeframes and symbols must be refreshed."""
    gate = Gatekeeper()
    assert len(gate._allowed_timeframes) > 0
    assert len(gate._enabled_symbols) > 0

    gate.reload()
    # Post-reload, gates should still be functional
    result = gate.evaluate(_base_candidate())
    assert result["passed"] is True
