"""Tests untuk semua trading agent — Tuyul Exception v.3."""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from agents.technical_structure import TechnicalStructureAgent
from agents.smart_money import SmartMoneyAgent
from agents.risk_reward import RiskRewardAgent
from agents.market_condition import MarketConditionAgent
from agents.news_event_risk import NewsEventRiskAgent
from agents.psychology_discipline import PsychologyDisciplineAgent
from schemas.agent_report import GateResult
from schemas.trade_candidate import Direction, Session, TradeCandidate


def make_candidate(overrides: dict | None = None) -> TradeCandidate:
    """Helper: buat TradeCandidate dengan context default yang valid."""
    base_context = {
        # TWMS - semua pass
        "htf_trend_aligned": True,
        "ema_alignment": True,
        "trendline_respect": True,
        "momentum_confirmed": True,
        "order_block_identified": True,
        "liquidity_sweep": True,
        "fair_value_gap": True,
        "volume_profile": True,
        "mtf_sync": True,
        "fibonacci_confluence": True,
        "candle_pattern": True,
        "divergence_confirmation": True,
        # Smart Money
        "order_block_freshness": "fresh",
        "liquidity_sweep_quality": "strong",
        "fvg_pips": 25.0,
        "volume_vs_avg_pct": 160.0,
        # Market
        "market_state": "TRENDING",
        "adx": 32.0,
        "htf_bias_aligned": True,
        "market_liquidity": "NORMAL",
        # News
        "news_risk_level": "LOW",
        "upcoming_news_events": [],
        "is_nfp_day": False,
        "is_central_bank_meeting_day": False,
        # Psychology
        "emotional_state": "NEUTRAL",
        "daily_loss_pct": 0.0,
        "consecutive_losses": 0,
        "is_revenge_trade": False,
        "is_fomo_trade": False,
        "daily_trades_count": 0,
        "consecutive_wins": 0,
        "system_ready": True,
        "account_balance": 100000,
        # Execution
        "orchestrator_approved": True,
        "session_quality": "HIGH",
    }
    if overrides:
        base_context.update(overrides)

    return TradeCandidate(
        candidate_id=str(uuid.uuid4()),
        instrument="EURUSD",
        direction=Direction.LONG,
        session=Session.LONDON,
        entry_price=1.08500,
        stop_loss=1.08000,
        take_profit=1.09500,
        lot_size=0.10,
        submitted_at=datetime.utcnow(),
        raw_context=base_context,
    )


# ── Technical Structure Agent ────────────────────────────────


@pytest.mark.asyncio
async def test_technical_structure_perfect():
    agent = TechnicalStructureAgent()
    candidate = make_candidate()
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.PASS
    assert report.details["passed"] == 12


@pytest.mark.asyncio
async def test_technical_structure_fail_below_threshold():
    # Hanya 9/12 pass
    agent = TechnicalStructureAgent()
    candidate = make_candidate({
        "htf_trend_aligned": False,
        "order_block_identified": False,
        "liquidity_sweep": False,
    })
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.FAIL
    assert report.details["passed"] < 11


# ── Smart Money Agent ────────────────────────────────────────


@pytest.mark.asyncio
async def test_smart_money_grade_a():
    agent = SmartMoneyAgent()
    candidate = make_candidate({
        "order_block_freshness": "fresh",
        "liquidity_sweep_quality": "strong",
        "fvg_pips": 30.0,
        "volume_vs_avg_pct": 160.0,
    })
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.PASS
    assert report.details["grade"] == "A"


@pytest.mark.asyncio
async def test_smart_money_fail_grade_c():
    agent = SmartMoneyAgent()
    candidate = make_candidate({
        "order_block_freshness": "stale",
        "liquidity_sweep_quality": "weak",
        "fvg_pips": 5.0,
        "volume_vs_avg_pct": 90.0,
    })
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.FAIL
    assert report.details["grade"] == "C"


# ── Risk Reward Agent ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_rr_passes_valid():
    agent = RiskRewardAgent()
    candidate = make_candidate()
    report = await agent.evaluate(candidate)
    # RR = (1.09500 - 1.08500) / (1.08500 - 1.08000) = 100/50 = 2.0
    assert report.gate_result == GateResult.PASS


@pytest.mark.asyncio
async def test_rr_fails_below_minimum():
    agent = RiskRewardAgent()
    # RR = 0.5/1.0 = 0.5 — below 2.0 minimum
    candidate = make_candidate()
    candidate.take_profit = 1.08750  # tiny profit
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.FAIL


# ── Market Condition Agent ────────────────────────────────────


@pytest.mark.asyncio
async def test_market_condition_trending_pass():
    agent = MarketConditionAgent()
    candidate = make_candidate({"market_state": "TRENDING", "adx": 30})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.PASS


@pytest.mark.asyncio
async def test_market_condition_choppy_fail():
    agent = MarketConditionAgent()
    candidate = make_candidate({"market_state": "CHOPPY", "adx": 10})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.FAIL


# ── News Event Risk Agent ─────────────────────────────────────


@pytest.mark.asyncio
async def test_news_low_risk_pass():
    agent = NewsEventRiskAgent()
    candidate = make_candidate({"news_risk_level": "LOW", "upcoming_news_events": []})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.PASS


@pytest.mark.asyncio
async def test_news_central_bank_fail():
    agent = NewsEventRiskAgent()
    candidate = make_candidate({"is_central_bank_meeting_day": True})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.FAIL


# ── Psychology Discipline Agent ────────────────────────────────


@pytest.mark.asyncio
async def test_psychology_ready_pass():
    agent = PsychologyDisciplineAgent()
    candidate = make_candidate({
        "emotional_state": "NEUTRAL",
        "daily_loss_pct": 0.0,
        "consecutive_losses": 0,
    })
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.PASS


@pytest.mark.asyncio
async def test_psychology_halt_on_revenge():
    agent = PsychologyDisciplineAgent()
    candidate = make_candidate({"is_revenge_trade": True})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.HALT


@pytest.mark.asyncio
async def test_psychology_halt_on_daily_loss():
    agent = PsychologyDisciplineAgent()
    candidate = make_candidate({"daily_loss_pct": 3.0})  # > 2.0 limit
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.HALT


@pytest.mark.asyncio
async def test_psychology_halt_on_emotional_state():
    agent = PsychologyDisciplineAgent()
    candidate = make_candidate({"emotional_state": "ANGRY"})
    report = await agent.evaluate(candidate)
    assert report.gate_result == GateResult.HALT
