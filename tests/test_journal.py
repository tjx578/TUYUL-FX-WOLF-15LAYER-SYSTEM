"""
Tests for Journal System (J1-J4)

Tests cover:
  - Schema validation (J1-J4 models)
  - JournalWriter file operations
  - JournalRouter event handling
  - GPT Bridge metrics computation
  - Enum validation
"""

import json

import pytest

from journal.journal_schema import (
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ReflectiveJournal,
    VerdictType,
    TradeOutcome,
    ProtectionAssessment,
)
from journal.journal_writer import JournalWriter
from journal.journal_router import JournalRouter
from journal.journal_gpt_bridge import compute_metrics
from utils.timezone_utils import now_utc


# ========================
# SCHEMA VALIDATION TESTS
# ========================

def test_context_journal_valid():
    """Test ContextJournal with valid data"""
    j1 = ContextJournal(
        timestamp=now_utc(),
        pair="EURUSD",
        session="LONDON",
        market_regime="TRENDING",
        news_lock=False,
        context_coherence=0.85,
        mta_alignment=True,
        technical_bias="BULLISH",
    )
    assert j1.pair == "EURUSD"
    assert j1.context_coherence == 0.85


def test_context_journal_invalid_coherence():
    """Test ContextJournal rejects invalid coherence (> 1.0)"""
    with pytest.raises(ValueError):
        ContextJournal(
            timestamp=now_utc(),
            pair="EURUSD",
            session="LONDON",
            market_regime="TRENDING",
            news_lock=False,
            context_coherence=1.5,  # Invalid: > 1.0
            mta_alignment=True,
            technical_bias="BULLISH",
        )


def test_context_journal_invalid_coherence_negative():
    """Test ContextJournal rejects negative coherence (< 0.0)"""
    with pytest.raises(ValueError):
        ContextJournal(
            timestamp=now_utc(),
            pair="EURUSD",
            session="LONDON",
            market_regime="TRENDING",
            news_lock=False,
            context_coherence=-0.5,  # Invalid: < 0.0
            mta_alignment=True,
            technical_bias="BULLISH",
        )


def test_decision_journal_valid():
    """Test DecisionJournal with valid data"""
    j2 = DecisionJournal(
        timestamp=now_utc(),
        pair="EURUSD",
        setup_id="EURUSD_20260210_120000",
        wolf_30_score=25,
        f_score=8,
        t_score=9,
        fta_score=8,
        exec_score=9,
        tii_sym=0.95,
        integrity_index=0.92,
        monte_carlo_win=0.68,
        conf12=0.88,
        verdict=VerdictType.EXECUTE_BUY,
        confidence="HIGH",
        wolf_status="PACK",
        gates_passed=9,
        gates_total=9,
        failed_gates=[],
        violations=[],
    )
    assert j2.wolf_30_score == 25
    assert j2.verdict == VerdictType.EXECUTE_BUY


def test_decision_journal_invalid_wolf_score():
    """Test DecisionJournal rejects wolf_30_score > 30"""
    with pytest.raises(ValueError):
        DecisionJournal(
            timestamp=now_utc(),
            pair="EURUSD",
            setup_id="EURUSD_20260210_120000",
            wolf_30_score=35,  # Invalid: > 30
            f_score=8,
            t_score=9,
            fta_score=8,
            exec_score=9,
            tii_sym=0.95,
            integrity_index=0.92,
            monte_carlo_win=0.68,
            conf12=0.88,
            verdict=VerdictType.EXECUTE_BUY,
            confidence="HIGH",
            wolf_status="PACK",
            gates_passed=9,
        )


def test_decision_journal_invalid_setup_id():
    """Test DecisionJournal rejects setup_id without underscore"""
    with pytest.raises(ValueError, match="setup_id must contain underscore"):
        DecisionJournal(
            timestamp=now_utc(),
            pair="EURUSD",
            setup_id="EURUSD20260210120000",  # Invalid: no underscore
            wolf_30_score=25,
            f_score=8,
            t_score=9,
            fta_score=8,
            exec_score=9,
            tii_sym=0.95,
            integrity_index=0.92,
            monte_carlo_win=0.68,
            conf12=0.88,
            verdict=VerdictType.EXECUTE_BUY,
            confidence="HIGH",
            wolf_status="PACK",
            gates_passed=9,
        )


def test_execution_journal_valid():
    """Test ExecutionJournal with valid data"""
    j3 = ExecutionJournal(
        timestamp=now_utc(),
        setup_id="EURUSD_20260210_120000",
        pair="EURUSD",
        direction="BUY",
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit_1=1.1100,
        rr_ratio=2.0,
        risk_percent=1.0,
        lot_size=0.01,
        sm_state="PENDING_ACTIVE",
    )
    assert j3.rr_ratio == 2.0
    assert j3.execution_mode == "TP1_ONLY"


def test_execution_journal_invalid_price():
    """Test ExecutionJournal rejects non-positive prices"""
    with pytest.raises(ValueError):
        ExecutionJournal(
            timestamp=now_utc(),
            setup_id="EURUSD_20260210_120000",
            pair="EURUSD",
            direction="BUY",
            entry_price=0,  # Invalid: must be > 0
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr_ratio=2.0,
            risk_percent=1.0,
            lot_size=0.01,
            sm_state="PENDING_ACTIVE",
        )


def test_reflective_journal_valid():
    """Test ReflectiveJournal with valid data"""
    j4 = ReflectiveJournal(
        timestamp=now_utc(),
        setup_id="EURUSD_20260210_120000",
        pair="EURUSD",
        outcome=TradeOutcome.WIN,
        did_system_protect=ProtectionAssessment.NO,
        was_rejection_correct=None,
        discipline_rating=9,
        override_attempted=False,
        learning_note="Good trade, followed system",
        system_adjustment_candidate=False,
    )
    assert j4.outcome == TradeOutcome.WIN
    assert j4.discipline_rating == 9


def test_reflective_journal_invalid_discipline():
    """Test ReflectiveJournal rejects discipline_rating > 10"""
    with pytest.raises(ValueError):
        ReflectiveJournal(
            timestamp=now_utc(),
            setup_id="EURUSD_20260210_120000",
            pair="EURUSD",
            outcome=TradeOutcome.WIN,
            did_system_protect=ProtectionAssessment.NO,
            discipline_rating=15,  # Invalid: > 10
        )


def test_reflective_journal_invalid_discipline_low():
    """Test ReflectiveJournal rejects discipline_rating < 1"""
    with pytest.raises(ValueError):
        ReflectiveJournal(
            timestamp=now_utc(),
            setup_id="EURUSD_20260210_120000",
            pair="EURUSD",
            outcome=TradeOutcome.WIN,
            did_system_protect=ProtectionAssessment.NO,
            discipline_rating=0,  # Invalid: < 1
        )


# ========================
# ENUM VALIDATION TESTS
# ========================

def test_verdict_type_enum():
    """Test VerdictType enum values"""
    assert VerdictType.EXECUTE_BUY.value == "EXECUTE_BUY"
    assert VerdictType.EXECUTE_SELL.value == "EXECUTE_SELL"
    assert VerdictType.HOLD.value == "HOLD"
    assert VerdictType.NO_TRADE.value == "NO_TRADE"


def test_trade_outcome_enum():
    """Test TradeOutcome enum values"""
    assert TradeOutcome.WIN.value == "WIN"
    assert TradeOutcome.LOSS.value == "LOSS"
    assert TradeOutcome.BREAKEVEN.value == "BREAKEVEN"
    assert TradeOutcome.SKIPPED.value == "SKIPPED"


def test_protection_assessment_enum():
    """Test ProtectionAssessment enum values"""
    assert ProtectionAssessment.YES.value == "YES"
    assert ProtectionAssessment.NO.value == "NO"
    assert ProtectionAssessment.UNCLEAR.value == "UNCLEAR"


# ========================
# JOURNAL WRITER TESTS
# ========================

def test_journal_writer_creates_file(tmp_path):
    """Test JournalWriter creates file in correct location"""
    writer = JournalWriter(base_dir=str(tmp_path))
    
    j1 = ContextJournal(
        timestamp=now_utc(),
        pair="EURUSD",
        session="LONDON",
        market_regime="TRENDING",
        news_lock=False,
        context_coherence=0.85,
        mta_alignment=True,
        technical_bias="BULLISH",
    )
    
    file_path = writer.write(j1)
    
    # Verify file exists
    assert file_path.exists()
    
    # Verify file is in date-based directory
    assert file_path.parent.parent == tmp_path
    
    # Verify filename format
    assert "_context_EURUSD.json" in file_path.name


def test_journal_writer_file_format(tmp_path):
    """Test JournalWriter creates correctly formatted JSON"""
    writer = JournalWriter(base_dir=str(tmp_path))
    
    j2 = DecisionJournal(
        timestamp=now_utc(),
        pair="EURUSD",
        setup_id="EURUSD_20260210_120000",
        wolf_30_score=25,
        f_score=8,
        t_score=9,
        fta_score=8,
        exec_score=9,
        tii_sym=0.95,
        integrity_index=0.92,
        monte_carlo_win=0.68,
        conf12=0.88,
        verdict=VerdictType.EXECUTE_BUY,
        confidence="HIGH",
        wolf_status="PACK",
        gates_passed=9,
    )
    
    file_path = writer.write(j2)
    
    # Read and parse JSON
    with open(file_path, "r") as f:
        content = json.load(f)
    
    # Verify structure
    assert "journal_type" in content
    assert "recorded_at" in content
    assert "data" in content
    assert content["journal_type"] == "decision"
    assert content["data"]["pair"] == "EURUSD"
    assert content["data"]["wolf_30_score"] == 25


# ========================
# JOURNAL ROUTER TESTS
# ========================

def test_journal_router_is_singleton():
    """Test JournalRouter is a singleton"""
    router1 = JournalRouter()
    router2 = JournalRouter()
    assert router1 is router2


def test_journal_router_increments_count(tmp_path):
    """Test JournalRouter increments event count"""
    # Create fresh router instance with temp directory
    from journal.journal_writer import JournalWriter
    
    router = JournalRouter()
    # Replace writer with one using temp dir
    router._writer = JournalWriter(base_dir=str(tmp_path))
    
    initial_count = router.get_event_count()
    
    j1 = ContextJournal(
        timestamp=now_utc(),
        pair="EURUSD",
        session="LONDON",
        market_regime="TRENDING",
        news_lock=False,
        context_coherence=0.85,
        mta_alignment=True,
        technical_bias="BULLISH",
    )
    
    router.record_context(j1)
    
    # Count should increase
    assert router.get_event_count() > initial_count


# ========================
# GPT BRIDGE METRICS TESTS
# ========================

def test_compute_metrics_empty():
    """Test compute_metrics with empty entries"""
    metrics = compute_metrics([])
    assert metrics["total_decisions"] == 0
    assert metrics["total_executions"] == 0
    assert metrics["rejection_rate"] == 0.0


def test_compute_metrics_with_decisions():
    """Test compute_metrics with sample decision entries"""
    entries = [
        {
            "journal_type": "decision",
            "data": {
                "verdict": "EXECUTE_BUY",
                "wolf_30_score": 25,
                "failed_gates": [],
            },
        },
        {
            "journal_type": "decision",
            "data": {
                "verdict": "HOLD",
                "wolf_30_score": 15,
                "failed_gates": ["gate_4_fta"],
            },
        },
        {
            "journal_type": "decision",
            "data": {
                "verdict": "NO_TRADE",
                "wolf_30_score": 10,
                "failed_gates": ["gate_4_fta", "gate_5_montecarlo"],
            },
        },
    ]
    
    metrics = compute_metrics(entries)
    
    assert metrics["total_decisions"] == 3
    assert metrics["verdict_counts"]["EXECUTE_BUY"] == 1
    assert metrics["verdict_counts"]["HOLD"] == 1
    assert metrics["verdict_counts"]["NO_TRADE"] == 1
    assert metrics["rejection_rate"] == 66.7  # 2 rejections out of 3
    assert len(metrics["top_failed_gates"]) > 0
    assert metrics["top_failed_gates"][0][0] == "gate_4_fta"


def test_compute_metrics_with_reflections():
    """Test compute_metrics with reflection entries"""
    entries = [
        {
            "journal_type": "reflection",
            "data": {
                "outcome": "WIN",
                "did_system_protect": "YES",
                "override_attempted": False,
            },
        },
        {
            "journal_type": "reflection",
            "data": {
                "outcome": "SKIPPED",
                "did_system_protect": "YES",
                "override_attempted": True,
            },
        },
    ]
    
    metrics = compute_metrics(entries)
    
    assert metrics["total_reflections"] == 2
    assert metrics["protection_score"] == 100.0
    assert metrics["override_count"] == 1
