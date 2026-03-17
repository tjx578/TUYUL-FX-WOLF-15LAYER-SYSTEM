"""Tests for STALE_THRESHOLDS_MS values in connectionState.ts.

BUG-6 fix: Aligns analysis-driven domain thresholds with the analysis loop
cadence (60s + execution buffer + network jitter ≈ 90s) to eliminate false
STALE DATA banners between analysis cycles.

These tests parse the TypeScript source file to verify the threshold values
are correct, making them resilient to accidental regression of the fix.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the TypeScript file relative to the repo root
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_CONNECTION_STATE_TS = (
    _REPO_ROOT / "dashboard" / "nextjs" / "src" / "lib" / "realtime" / "connectionState.ts"
)


def _parse_stale_thresholds() -> dict[str, int]:
    """Parse STALE_THRESHOLDS_MS from connectionState.ts.

    Reads the TypeScript source and extracts {domain: ms} pairs from the
    STALE_THRESHOLDS_MS object literal.
    """
    source = _CONNECTION_STATE_TS.read_text(encoding="utf-8")

    # Find the STALE_THRESHOLDS_MS object block
    match = re.search(
        r"STALE_THRESHOLDS_MS\s*:\s*Record<[^>]+>\s*=\s*\{([^}]+)\}",
        source,
        re.DOTALL,
    )
    if not match:
        raise ValueError(
            f"Could not locate STALE_THRESHOLDS_MS in {_CONNECTION_STATE_TS}"
        )

    block = match.group(1)
    thresholds: dict[str, int] = {}

    for line in block.splitlines():
        # Match lines like: "  prices: 5000,  // comment"
        entry = re.match(r"\s*(\w+)\s*:\s*(\d+)", line)
        if entry:
            thresholds[entry.group(1)] = int(entry.group(2))

    return thresholds


class TestConnectionStateThresholds:
    """Verify STALE_THRESHOLDS_MS are properly aligned with the analysis cadence."""

    def setup_method(self) -> None:
        self.thresholds = _parse_stale_thresholds()

    def test_file_exists(self) -> None:
        """connectionState.ts must exist in the expected location."""
        assert _CONNECTION_STATE_TS.exists(), (
            f"connectionState.ts not found at {_CONNECTION_STATE_TS}"
        )

    def test_all_expected_domains_present(self) -> None:
        """All expected domain keys must be present in STALE_THRESHOLDS_MS."""
        expected_domains = {
            "prices", "trades", "risk", "equity",
            "signals", "verdicts", "pipeline", "candles", "alerts",
        }
        assert expected_domains.issubset(self.thresholds.keys()), (
            f"Missing domains: {expected_domains - self.thresholds.keys()}"
        )

    # ── Analysis-driven domains (90s — aligned with 60s loop + buffer) ──────

    def test_signals_threshold_aligned_with_analysis_loop(self) -> None:
        """signals threshold must be ≥ 90000ms (60s loop + ~30s buffer)."""
        assert self.thresholds["signals"] >= 90_000, (
            f"signals={self.thresholds['signals']}ms is too aggressive for a 60s analysis loop"
        )

    def test_verdicts_threshold_aligned_with_analysis_loop(self) -> None:
        """verdicts threshold must be ≥ 90000ms (verdicts update per analysis cycle)."""
        assert self.thresholds["verdicts"] >= 90_000, (
            f"verdicts={self.thresholds['verdicts']}ms will cause false STALE during 60s analysis cycles"
        )

    def test_pipeline_threshold_aligned_with_analysis_loop(self) -> None:
        """pipeline threshold must be ≥ 90000ms (pipeline results follow analysis loop)."""
        assert self.thresholds["pipeline"] >= 90_000, (
            f"pipeline={self.thresholds['pipeline']}ms will cause false STALE during 60s analysis cycles"
        )

    # ── Tick/stream-driven domains (faster cadence expected) ─────────────────

    def test_prices_threshold_detects_feed_failure(self) -> None:
        """prices threshold must be ≤ 10000ms — tick data should arrive frequently."""
        assert self.thresholds["prices"] <= 10_000, (
            f"prices={self.thresholds['prices']}ms is too permissive for WS tick data"
        )

    def test_prices_threshold_not_too_aggressive(self) -> None:
        """prices threshold must be ≥ 1000ms — avoid spurious STALE on minor jitter."""
        assert self.thresholds["prices"] >= 1_000, (
            f"prices={self.thresholds['prices']}ms is too aggressive and will cause false STALE"
        )

    def test_candles_threshold_reasonable(self) -> None:
        """candles threshold must be between 5s and 60s (partial updates are frequent)."""
        assert 5_000 <= self.thresholds["candles"] <= 60_000, (
            f"candles={self.thresholds['candles']}ms is outside the reasonable 5s-60s range"
        )

    def test_analysis_driven_thresholds_much_higher_than_tick_thresholds(self) -> None:
        """Analysis-driven domains must have significantly longer thresholds than tick domains."""
        analysis_min = min(
            self.thresholds["signals"],
            self.thresholds["verdicts"],
            self.thresholds["pipeline"],
        )
        tick_max = max(
            self.thresholds["prices"],
            self.thresholds["trades"],
        )
        assert analysis_min > tick_max * 5, (
            f"Analysis thresholds ({analysis_min}ms) should be ≫ tick thresholds ({tick_max}ms)"
        )

    # ── Exact values for the BUG-6 fix (regression guard) ───────────────────

    def test_signals_exact_value_is_90000(self) -> None:
        """signals must be exactly 90000ms as per BUG-6 fix."""
        assert self.thresholds["signals"] == 90_000

    def test_verdicts_exact_value_is_90000(self) -> None:
        """verdicts must be exactly 90000ms as per BUG-6 fix."""
        assert self.thresholds["verdicts"] == 90_000

    def test_pipeline_exact_value_is_90000(self) -> None:
        """pipeline must be exactly 90000ms as per BUG-6 fix."""
        assert self.thresholds["pipeline"] == 90_000

    def test_prices_exact_value_is_5000(self) -> None:
        """prices must be exactly 5000ms as per BUG-6 fix."""
        assert self.thresholds["prices"] == 5_000

    def test_candles_exact_value_is_20000(self) -> None:
        """candles must be exactly 20000ms as per BUG-6 fix (was 1500ms — too aggressive)."""
        assert self.thresholds["candles"] == 20_000

    def test_alerts_exact_value_is_60000(self) -> None:
        """alerts must be exactly 60000ms as per BUG-6 fix (was 30000ms)."""
        assert self.thresholds["alerts"] == 60_000
