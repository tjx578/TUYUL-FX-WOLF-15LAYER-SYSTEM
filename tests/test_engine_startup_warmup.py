"""Tests for engine startup warmup readiness checks.

Verifies that:
- The engine uses H1 (not M15) for its Redis readiness gate.
- WARMUP_MIN_BARS does not include M15 (M15 arrives from tick data,
  not REST, so it must never block pipeline startup).
"""
from __future__ import annotations

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

# ── Pipeline warmup gate tests ──────────────────────────────────────


def test_warmup_min_bars_does_not_include_m15() -> None:
    """M15 must not be in WARMUP_MIN_BARS.

    M15 candles are built from tick data (CandleBuilder), not from REST.
    The first M15 candle only completes ~15 minutes after WebSocket
    connects.  Requiring M15 at startup would block all 30 pairs for
    the first 15+ minutes on every cold start.
    """
    assert "M15" not in WolfConstitutionalPipeline.WARMUP_MIN_BARS, (
        "M15 must not be in WARMUP_MIN_BARS — it arrives from tick stream, "
        "not REST warmup.  Remove it to unblock pipeline startup."
    )


def test_warmup_min_bars_requires_h1_h4_d1() -> None:
    """H1, H4, D1 must remain in WARMUP_MIN_BARS (seeded by ingest via REST)."""
    for tf in ("H1", "H4", "D1"):
        assert tf in WolfConstitutionalPipeline.WARMUP_MIN_BARS, (
            f"{tf} should remain in WARMUP_MIN_BARS — it is seeded by ingest "
            "via Finnhub REST warmup and is available at startup."
        )


# ── Engine _seed_from_redis H1 readiness check ─────────────────────


def test_seed_from_redis_checks_h1_not_m15() -> None:
    """_seed_from_redis must gate on H1 data availability, not M15.

    M15 is built from tick data and cannot exist in Redis at startup.
    Gating on M15 would cause the engine to exhaust all retries and
    enter DEGRADED mode before analysis ever starts.

    We verify this by reading the source of startup/candle_seeding.py and checking that
    the readiness dict uses H1 and no M15 gate is present.
    """
    import pathlib  # noqa: PLC0415
    import re  # noqa: PLC0415

    src = pathlib.Path(__file__).parents[1].joinpath("startup", "candle_seeding.py").read_text()

    # Isolate just the _seed_from_redis function body
    match = re.search(
        r"async def _seed_from_redis\([^)]*\).*?(?=\nasync def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert match, "_seed_from_redis not found in startup/candle_seeding.py"
    fn_src = match.group(0)

    # H1 must be the readiness key
    assert '"H1"' in fn_src or "'H1'" in fn_src, (
        "_seed_from_redis does not check H1 readiness — "
        "H1 is always seeded by ingest via REST and must be the startup gate."
    )

    # M15 must NOT appear as a dict key in a readiness check
    # (it may appear in log message strings, so we look for dict-key patterns)
    m15_gate = re.search(r'["\']M15["\']\s*:', fn_src)
    assert m15_gate is None, (
        "_seed_from_redis still has an M15 gate — "
        f"found pattern at: {m15_gate.group()!r}. "
        "Remove it; M15 arrives from ticks ~15 min after WebSocket connects."
    )

