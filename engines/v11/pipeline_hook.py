"""
V11 Pipeline Hook - Post-Pipeline Integration Point

The SOLE touchpoint between v11 and existing pipeline.
Reads PipelineResult, runs V11DataAdapter + ExtremeSelectivityGate, returns V11Overlay.

Features:
- enabled master switch
- require_l12_execute flag (skip v11 if L12 didn't approve)
- Lazy engine loading to prevent circular imports
- Full timing/latency tracking
- Structured logging

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11, is_v11_enabled


@dataclass(frozen=True)
class V11Overlay:
    """
    V11 post-pipeline overlay result.
    
    This is the output of the v11 hook that overlays on top of PipelineResult.
    """
    
    enabled: bool
    should_trade: bool  # Final recommendation: L12 + v11 consensus
    gate_result: dict[str, Any] | None
    adapter_input: dict[str, Any] | None
    latency_ms: float
    skipped_reason: str | None = None
    error: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON consumption."""
        return {
            "enabled": self.enabled,
            "should_trade": self.should_trade,
            "gate_result": self.gate_result,
            "adapter_input": self.adapter_input,
            "latency_ms": self.latency_ms,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
        }


class V11PipelineHook:
    """
    Post-pipeline hook for v11 extreme selectivity filtering.
    
    Decision Matrix:
    - L12=EXECUTE AND v11=ALLOW → ✅ TRADE (Sniper Entry)
    - L12=EXECUTE AND v11=BLOCK → ❌ NO TRADE (v11 veto)
    - L12=HOLD/NO_TRADE AND v11=* → ❌ NO TRADE (L12 authority preserved)
    
    v11 can ONLY reduce trades (block EXECUTE), never override HOLD.
    """
    
    def __init__(self) -> None:
        self._enabled = is_v11_enabled()
        self._require_l12_execute = get_v11("governance.require_l12_execute", True)
        self._max_latency_ms = get_v11("governance.max_latency_ms", 100)
        
        # Lazy-loaded components (prevent circular imports)
        self._data_adapter = None
        self._selectivity_gate = None
    
    def evaluate(
        self,
        pipeline_result: Any,  # PipelineResult
        symbol: str,
        timeframe: str = "H1",
    ) -> V11Overlay:
        """
        Evaluate pipeline result through v11 sniper filter.
        
        Args:
            pipeline_result: Output from WolfConstitutionalPipeline
            symbol: Trading symbol
            timeframe: Timeframe for analysis
        
        Returns:
            V11Overlay with final trade recommendation
        """
        start_time = time.perf_counter()
        
        # Check if v11 is enabled
        if not self._enabled:
            return self._disabled_overlay(time.perf_counter() - start_time)
        
        try:
            # Extract L12 verdict
            l12_verdict = self._extract_l12_verdict(pipeline_result)
            
            # If L12 didn't approve, skip v11 (preserve L12 authority)
            if self._require_l12_execute and l12_verdict != "EXECUTE":
                latency = (time.perf_counter() - start_time) * 1000
                return V11Overlay(
                    enabled=True,
                    should_trade=False,
                    gate_result=None,
                    adapter_input=None,
                    latency_ms=latency,
                    skipped_reason=f"L12_verdict={l12_verdict}",
                )
            
            # Load v11 components (lazy)
            self._ensure_components_loaded()
            
            # Extract synthesis from pipeline result
            synthesis = self._extract_synthesis(pipeline_result)
            
            # Collect data for gate
            gate_input = self._data_adapter.collect(synthesis, symbol, timeframe)
            
            if gate_input is None:
                latency = (time.perf_counter() - start_time) * 1000
                return V11Overlay(
                    enabled=True,
                    should_trade=False,
                    gate_result=None,
                    adapter_input=None,
                    latency_ms=latency,
                    error="Failed to collect gate input data",
                )
            
            # Run gate evaluation
            gate_result = self._selectivity_gate.evaluate(gate_input)
            
            latency = (time.perf_counter() - start_time) * 1000
            
            # Check latency budget
            if latency > self._max_latency_ms:
                logger.warning(
                    f"V11 latency exceeded budget: {latency:.2f}ms > {self._max_latency_ms}ms"
                )
            
            # Determine final recommendation
            should_trade = self._compute_final_decision(l12_verdict, gate_result)
            
            # Log decision
            self._log_decision(symbol, l12_verdict, gate_result, should_trade, latency)
            
            return V11Overlay(
                enabled=True,
                should_trade=should_trade,
                gate_result=gate_result.to_dict(),
                adapter_input=self._serialize_gate_input(gate_input),
                latency_ms=latency,
            )
            
        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            logger.error(f"V11PipelineHook: Error during evaluation: {e}")
            
            return V11Overlay(
                enabled=True,
                should_trade=False,
                gate_result=None,
                adapter_input=None,
                latency_ms=latency,
                error=str(e),
            )
    
    def _ensure_components_loaded(self) -> None:
        """Lazy-load v11 components to prevent circular imports."""
        if self._data_adapter is None:
            from engines.v11.data_adapter import V11DataAdapter  # noqa: PLC0415
            self._data_adapter = V11DataAdapter()
        
        if self._selectivity_gate is None:
            from engines.v11.extreme_selectivity_gate import ExtremeSelectivityGateV11  # noqa: PLC0415
            self._selectivity_gate = ExtremeSelectivityGateV11()
    
    def _extract_l12_verdict(self, pipeline_result: Any) -> str:
        """Extract L12 verdict from pipeline result."""
        try:
            # PipelineResult has l12_verdict dict
            l12 = pipeline_result.l12_verdict
            return l12.get("verdict", "NO_TRADE")
        except Exception:
            return "NO_TRADE"
    
    def _extract_synthesis(self, pipeline_result: Any) -> dict[str, Any]:
        """Extract synthesis dict from pipeline result."""
        try:
            return pipeline_result.synthesis
        except Exception:
            return {}
    
    def _compute_final_decision(self, l12_verdict: str, gate_result: Any) -> bool:
        """
        Compute final trade decision based on L12 + v11.
        
        Decision Matrix:
        - L12=EXECUTE AND v11=ALLOW → TRUE
        - L12=EXECUTE AND v11=BLOCK → FALSE
        - L12≠EXECUTE → FALSE (L12 authority preserved)
        """
        if l12_verdict != "EXECUTE":
            return False
        
        # v11 can only veto EXECUTE
        from engines.v11.extreme_selectivity_gate import GateVerdict  # noqa: PLC0415
        
        return gate_result.verdict == GateVerdict.ALLOW
    
    def _serialize_gate_input(self, gate_input: Any) -> dict[str, Any]:
        """Serialize gate input for logging/debugging."""
        try:
            return {
                "regime_label": gate_input.regime_label,
                "regime_confidence": gate_input.regime_confidence,
                "vol_state": gate_input.vol_state,
                "cluster_exposure": gate_input.cluster_exposure,
                "discipline_score": gate_input.discipline_score,
                "eaf_score": gate_input.eaf_score,
                "monte_carlo_win": gate_input.monte_carlo_win,
                "posterior": gate_input.posterior,
            }
        except Exception:
            return {}
    
    def _log_decision(
        self,
        symbol: str,
        l12_verdict: str,
        gate_result: Any,
        should_trade: bool,
        latency: float,
    ) -> None:
        """Log v11 decision with structured data."""
        log_level = get_v11("governance.log_level", "INFO")
        
        if log_level == "DEBUG":
            logger.debug(
                f"V11 Decision: symbol={symbol} L12={l12_verdict} "
                f"v11={gate_result.verdict.value} final={should_trade} "
                f"score={gate_result.score:.3f} latency={latency:.2f}ms"
            )
        elif log_level == "INFO" and gate_result.veto_triggered:
            logger.info(
                f"V11 VETO: symbol={symbol} reasons={gate_result.veto_reasons}"
            )
    
    def _disabled_overlay(self, elapsed: float) -> V11Overlay:
        """Return overlay indicating v11 is disabled."""
        return V11Overlay(
            enabled=False,
            should_trade=True,  # Pass-through when disabled
            gate_result=None,
            adapter_input=None,
            latency_ms=elapsed * 1000,
        )
