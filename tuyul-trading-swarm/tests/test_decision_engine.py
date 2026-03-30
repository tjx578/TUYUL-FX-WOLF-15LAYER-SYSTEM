"""Tests untuk DecisionEngine — aggregasi dan verdict logic."""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from agents.psychology_discipline import PsychologyDisciplineAgent
from core.decision_engine import DecisionEngine
from schemas.agent_report import AgentReport, GateResult
from schemas.trade_candidate import Direction, FinalVerdict, Session, TradeCandidate


def make_candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id=str(uuid.uuid4()),
        instrument="EURUSD",
        direction=Direction.LONG,
        session=Session.LONDON,
        entry_price=1.08500,
        stop_loss=1.08000,
        take_profit=1.09500,
        raw_context={},
    )


def pass_report(name: str, agent_id: int, cid: str) -> AgentReport:
    return AgentReport(
        agent_id=agent_id,
        agent_name=name,
        candidate_id=cid,
        gate_result=GateResult.PASS,
        reason=f"{name} passed",
    )


def fail_report(name: str, agent_id: int, cid: str) -> AgentReport:
    return AgentReport(
        agent_id=agent_id,
        agent_name=name,
        candidate_id=cid,
        gate_result=GateResult.FAIL,
        reason=f"{name} failed",
        disqualifiers=[f"{name}_disqualifier"],
    )


def halt_report(name: str, agent_id: int, cid: str) -> AgentReport:
    return AgentReport(
        agent_id=agent_id,
        agent_name=name,
        candidate_id=cid,
        gate_result=GateResult.HALT,
        reason=f"HALT from {name}",
    )


def test_all_pass_gives_execute():
    engine = DecisionEngine()
    candidate = make_candidate()
    cid = candidate.candidate_id

    reports = [
        pass_report("technical_structure", 3, cid),
        pass_report("smart_money", 4, cid),
        pass_report("risk_reward", 5, cid),
        pass_report("market_condition", 6, cid),
        pass_report("news_event_risk", 7, cid),
        pass_report("psychology_discipline", 8, cid),
    ]

    packet = engine.aggregate(candidate, reports)
    assert packet.final_verdict == FinalVerdict.EXECUTE


def test_one_fail_gives_skip():
    engine = DecisionEngine()
    candidate = make_candidate()
    cid = candidate.candidate_id

    reports = [
        pass_report("technical_structure", 3, cid),
        fail_report("smart_money", 4, cid),  # Smart money gagal
        pass_report("risk_reward", 5, cid),
        pass_report("market_condition", 6, cid),
        pass_report("news_event_risk", 7, cid),
        pass_report("psychology_discipline", 8, cid),
    ]

    packet = engine.aggregate(candidate, reports)
    assert packet.final_verdict == FinalVerdict.SKIP
    assert "smart_money" in packet.failed_gates


def test_halt_overrides_all():
    engine = DecisionEngine()
    candidate = make_candidate()
    cid = candidate.candidate_id

    # Semua teknikal pass, tapi psychology HALT
    reports = [
        pass_report("technical_structure", 3, cid),
        pass_report("smart_money", 4, cid),
        pass_report("risk_reward", 5, cid),
        pass_report("market_condition", 6, cid),
        pass_report("news_event_risk", 7, cid),
        halt_report("psychology_discipline", 8, cid),  # HALT!
    ]

    packet = engine.aggregate(candidate, reports)
    assert packet.final_verdict == FinalVerdict.HALT


def test_multiple_fails_all_recorded():
    engine = DecisionEngine()
    candidate = make_candidate()
    cid = candidate.candidate_id

    reports = [
        fail_report("technical_structure", 3, cid),
        fail_report("smart_money", 4, cid),
        fail_report("market_condition", 6, cid),
        pass_report("risk_reward", 5, cid),
        pass_report("news_event_risk", 7, cid),
        pass_report("psychology_discipline", 8, cid),
    ]

    packet = engine.aggregate(candidate, reports)
    assert packet.final_verdict == FinalVerdict.SKIP
    assert len(packet.failed_gates) == 3
