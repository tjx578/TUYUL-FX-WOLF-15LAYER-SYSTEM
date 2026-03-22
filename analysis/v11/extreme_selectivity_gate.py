"""
V11 Extreme Selectivity Gate — hardened with input validation & type safety.

Analysis zone only. Produces a gate result; no execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from analysis.v11.models import GateVerdict, V11GateInput, V11GateResult

logger = logging.getLogger(__name__)


@dataclass
class V11Thresholds:
    """Configurable thresholds for the selectivity gate."""

    min_wolf_score: float = 0.75
    min_tii_score: float = 0.60
    min_frpc_score: float = 0.60
    min_confluence_score: float = 0.65
    max_spread_ratio: float = 0.25  # spread must be < 25% of ATR
    min_atr: float = 0.0001  # minimum ATR to consider volatility valid
    min_pass_ratio: float = 0.80  # fraction of checks that must pass
    require_htf_alignment: bool = True
    require_session_valid: bool = True
    require_news_clear: bool = True
    require_momentum: bool = True


class ExtremeSelectivityGateV11:
    """
    Gate that decides whether a candidate passes the V11 extreme-selectivity
    filter.  Returns a structured V11GateResult — never raises on bad input.
    """

    def __init__(self, thresholds: V11Thresholds | None = None) -> None:
        self.thresholds = thresholds or V11Thresholds()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, data: dict | V11GateInput) -> V11GateResult:
        """Evaluate a candidate.  Accepts raw dict OR validated V11GateInput."""
        inp = self._coerce_input(data)
        checks = self._run_checks(inp)

        passed = sum(1 for ok, _ in checks if ok)
        total = len(checks)
        failed = tuple(reason for ok, reason in checks if not ok)

        if total == 0:
            return V11GateResult(
                verdict=GateVerdict.SKIP,
                overall_score=0.0,
                passed_checks=0,
                total_checks=0,
                failed_criteria=("no_checks_available",),
            )

        ratio = passed / total
        verdict = GateVerdict.PASS if ratio >= self.thresholds.min_pass_ratio else GateVerdict.FAIL

        overall_score = self._compute_score(inp, ratio)

        result = V11GateResult(
            verdict=verdict,
            overall_score=round(overall_score, 4),
            passed_checks=passed,
            total_checks=total,
            failed_criteria=failed,
            details={
                "symbol": inp.symbol,
                "timeframe": inp.timeframe,
                "pass_ratio": round(ratio, 4),
                "scores": {
                    "wolf": inp.wolf_score,
                    "tii": inp.tii_score,
                    "frpc": inp.frpc_score,
                    "confluence": inp.confluence_score,
                },
            },
        )

        logger.info(
            "V11 Gate [%s %s]: %s (%d/%d) score=%.4f failed=%s",
            inp.symbol,
            inp.timeframe,
            result.verdict.value,
            passed,
            total,
            overall_score,
            failed or "none",
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _coerce_input(self, data: dict | V11GateInput) -> V11GateInput:
        """Safely coerce any input to V11GateInput.  Never raises."""
        if isinstance(data, V11GateInput):
            return data
        try:
            return V11GateInput.from_dict(data if isinstance(data, dict) else {})
        except Exception:
            logger.warning("V11 Gate: input coercion failed, using empty defaults")
            return V11GateInput()

    def _run_checks(self, inp: V11GateInput) -> list[tuple[bool, str]]:
        """Return list of (passed, criterion_name) tuples."""
        t = self.thresholds
        checks: list[tuple[bool, str]] = [
            (inp.wolf_score >= t.min_wolf_score, "wolf_score_below_threshold"),
            (inp.tii_score >= t.min_tii_score, "tii_score_below_threshold"),
            (inp.frpc_score >= t.min_frpc_score, "frpc_score_below_threshold"),
            (inp.confluence_score >= t.min_confluence_score, "confluence_below_threshold"),
        ]

        if t.require_htf_alignment:
            checks.append((inp.htf_alignment, "htf_not_aligned"))

        if t.require_session_valid:
            checks.append((inp.session_valid, "session_invalid"))

        if t.require_news_clear:
            checks.append((inp.news_clear, "news_not_clear"))

        if t.require_momentum:
            checks.append((inp.momentum_confirmed, "momentum_not_confirmed"))

        # Volatility / spread checks (only if ATR data is available)
        if inp.atr_value >= t.min_atr:
            checks.append((inp.spread_ratio <= t.max_spread_ratio, "spread_too_wide"))
        else:
            checks.append((False, "atr_too_low_or_missing"))

        return checks

    def _compute_score(self, inp: V11GateInput, pass_ratio: float) -> float:
        """Weighted composite score (0.0–1.0)."""
        score_component = (
            inp.wolf_score * 0.30 + inp.tii_score * 0.20 + inp.frpc_score * 0.20 + inp.confluence_score * 0.30
        )
        # Blend: 70% from scores, 30% from pass ratio
        return score_component * 0.70 + pass_ratio * 0.30
