from __future__ import annotations

from typing import Any

import pytest

from pipeline.warmup_utils import WarmupStatus
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def _warmup_ready(raw: Any, *, required: int) -> WarmupStatus:
    _ = raw
    return WarmupStatus(ready=True, bars=required, required=required, missing=0)


class _BusStub:
    def check_warmup(self, symbol: str, min_bars: dict[str, int]) -> dict[str, Any]:
        return {"ready": True, "bars": {}, "required": {}, "missing": {}}

    def get_trade_history(self, symbol: str, lookback: int = 200) -> list[float]:
        return []

    def get_conditioned_returns(self, symbol: str, count: int | None = None) -> list[float]:
        return []

    def get_conditioning_meta(self, symbol: str) -> dict[str, Any] | None:
        return None

    def get_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        if timeframe == "H1":
            return [
                {"close": 1.1000},
                {"close": 1.1002},
                {"close": 1.1001},
                {"close": 1.1003},
                {"close": 1.1004},
                {"close": 1.1006},
                {"close": 1.1005},
            ]
        return []

    def get_account_state(self, symbol: str) -> dict[str, Any]:
        return {}


class _L1:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {"valid": True, "valid_context": True, "volatility_level": "NORMAL"}


class _L2:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {"valid": True, "status": "ok"}


class _L3:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {"valid": True, "trend": "BULLISH"}


class _L4:
    def score(self, l1: dict[str, Any], l2: dict[str, Any], l3: dict[str, Any]) -> dict[str, Any]:
        return {"technical_score": 72, "directional_bias": 0.7}


class _L5:
    def analyze(self, symbol: str, volatility_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"current_drawdown": 0.0, "consecutive_losses": 0}


class _L7:
    last_trade_returns: list[float] | None = None

    def analyze(
        self,
        symbol: str,
        *,
        technical_score: int = 0,
        trade_returns: list[float] | None = None,
        prior_wins: int = 0,
        prior_losses: int = 0,
    ) -> dict[str, Any]:
        self.last_trade_returns = trade_returns
        return {
            "symbol": symbol,
            "win_probability": 65.0,
            "profit_factor": 1.7,
            "conf12_raw": 0.81,
            "bayesian_posterior": 0.62,
            "bayesian_ci_low": 0.55,
            "bayesian_ci_high": 0.68,
            "risk_of_ruin": 0.1,
            "expected_value": 0.02,
            "max_drawdown": -0.08,
            "mc_passed_threshold": True,
            "simulations": 100,
            "validation": "PASS",
            "valid": True,
        }


class _L8:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {"tii_score": 0.8, "integrity_index": 0.82}


class _L9:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {"confidence": 0.73, "liquidity_score": 0.71}


class _L10:
    def analyze(self, risk_ok: bool, smc_confidence: float) -> dict[str, Any]:
        return {"position_sizing_ok": risk_ok, "score": smc_confidence}


class _L11:
    def calculate_rr(self, symbol: str, direction: str) -> dict[str, Any]:
        return {
            "rr": 2.0,
            "entry_price": 1.1006,
            "stop_loss": 1.0990,
            "take_profit_1": 1.1040,
        }


class _L6:
    lrce_block_threshold = 0.6

    def _compute_lrce(self, enrichment_input: dict[str, Any]) -> float:
        return 0.0

    def analyze(
        self,
        *,
        rr: float,
        trade_returns: list[float] | None = None,
        account_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "risk_ok": True,
            "risk_status": "OK",
            "propfirm_compliant": True,
            "max_risk_pct": 1.0,
            "warnings": [],
            "drawdown_level": "LEVEL_0",
            "risk_multiplier": 1.0,
        }


class _Macro:
    def analyze(self, symbol: str) -> dict[str, Any]:
        return {
            "regime": "TREND",
            "phase": "NEUTRAL",
            "macro_vol_ratio": 1.0,
            "alignment": True,
            "liquidity": {},
            "bias_override": {},
        }


class _MacroVol:
    def get_state(self) -> dict[str, Any]:
        return {}


class _EnrichmentResult:
    enrichment_score = 0.0
    errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {}


class _Enrichment:
    def run(self, **kwargs: Any) -> _EnrichmentResult:
        return _EnrichmentResult()


class _L15:
    def compute_meta(self, **kwargs: Any) -> dict[str, Any]:
        return {"meta_integrity": 1.0}

    def enforce_sovereignty(self, **kwargs: Any) -> dict[str, Any]:
        return {"downgraded": False}


class _L13:
    def reflect(self, symbol: str, historical_verdicts: list[dict[str, Any]], current_layer_results: dict[str, Any]) -> dict[str, Any]:
        return {"abg_score": 0.8, "meta_integrity": 1.0}


def test_pipeline_fallback_uses_candle_conditioned_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pipeline.wolf_constitutional_pipeline.normalize_warmup",
        _warmup_ready,
    )

    pipe = WolfConstitutionalPipeline()

    l7 = _L7()

    pipe.__dict__.update(
        {
            "_context_bus": _BusStub(),
            "_l1": _L1(),
            "_l2": _L2(),
            "_l3": _L3(),
            "_l4": _L4(),
            "_l5": _L5(),
            "_l6": _L6(),
            "_l7": l7,
            "_l8": _L8(),
            "_l9": _L9(),
            "_l10": _L10(),
            "_l11": _L11(),
            "_macro": _Macro(),
            "_macro_vol": _MacroVol(),
            "_enrichment": _Enrichment(),
            "_l13_engine": None,
            "_l15_engine": _L15(),
        }
    )

    pipe._ensure_analyzers = lambda: None  # type: ignore[assignment]
    pipe._ensure_governance_engines = lambda: None  # type: ignore[assignment]
    pipe._get_l13_engine = lambda: _L13()  # type: ignore[assignment]
    pipe._get_l15_engine = lambda: _L15()  # type: ignore[assignment]
    pipe._build_l14_json = lambda **kwargs: {}  # type: ignore[assignment]
    pipe._compute_vault_sync = lambda synthesis, l12_verdict, reflective: {  # type: ignore[assignment]
        "execution_rights": "GRANTED",
        "vault_sync": 1.0,
        "meta_integrity": 1.0,
    }

    result = pipe.execute("EURUSD")

    assert isinstance(l7.last_trade_returns, list)
    assert l7.last_trade_returns is not None
    assert len(l7.last_trade_returns) > 0

    cond = result["synthesis"]["system"].get("signal_conditioning", {})
    assert cond.get("source") == "candle_H1"
    assert int(cond.get("samples_out", 0)) > 0
