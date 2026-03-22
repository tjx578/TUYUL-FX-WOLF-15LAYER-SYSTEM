from __future__ import annotations

from datetime import UTC, datetime

from journal.journal_router import journal_router
from journal.journal_schema import (
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ProtectionAssessment,
    ReflectiveJournal,
    TradeOutcome,
    VerdictType,
)


class TradeJournalAutomationService:
    """Automates J1/J2/J3/J4 writes from dashboard trade lifecycle."""

    def __init__(self) -> None:
        self._setup_by_signal: dict[str, str] = {}

    def on_signal_taken(self, trade: dict) -> None:
        now = datetime.now(UTC)
        pair = str(trade.get("pair", "UNKNOWN"))
        signal_id = str(trade.get("signal_id", ""))
        setup_id = self._setup_by_signal.setdefault(signal_id, f"{pair}_{int(now.timestamp())}")

        journal_router.record_context(
            ContextJournal(
                timestamp=now,
                pair=pair,
                session="UNKNOWN",
                market_regime="UNKNOWN",
                news_lock=False,
                context_coherence=0.5,
                mta_alignment=True,
                technical_bias="NEUTRAL",
            )
        )

        direction = str(trade.get("direction", "BUY")).upper()
        verdict = VerdictType.EXECUTE_BUY if direction == "BUY" else VerdictType.EXECUTE_SELL
        journal_router.record_decision(
            DecisionJournal(
                timestamp=now,
                pair=pair,
                setup_id=setup_id,
                wolf_30_score=0,
                f_score=0,
                t_score=0,
                fta_score=0,
                exec_score=0,
                tii_sym=0.0,
                integrity_index=0.0,
                monte_carlo_win=0.0,
                conf12=0.0,
                verdict=verdict,
                confidence="MEDIUM",
                wolf_status="SCOUT",
                gates_passed=0,
                gates_total=9,
                failed_gates=[],
                violations=[],
                primary_rejection_reason=None,
            )
        )

    def on_signal_skipped(self, signal_id: str, pair: str, reason: str) -> None:
        now = datetime.now(UTC)
        setup_id = self._setup_by_signal.setdefault(signal_id, f"{pair}_{int(now.timestamp())}")

        journal_router.record_decision(
            DecisionJournal(
                timestamp=now,
                pair=pair,
                setup_id=setup_id,
                wolf_30_score=0,
                f_score=0,
                t_score=0,
                fta_score=0,
                exec_score=0,
                tii_sym=0.0,
                integrity_index=0.0,
                monte_carlo_win=0.0,
                conf12=0.0,
                verdict=VerdictType.NO_TRADE,
                confidence="LOW",
                wolf_status="NO_HUNT",
                gates_passed=0,
                gates_total=9,
                failed_gates=[],
                violations=[],
                primary_rejection_reason=reason,
            )
        )

        journal_router.record_reflection(
            ReflectiveJournal(
                timestamp=now,
                setup_id=setup_id,
                pair=pair,
                outcome=TradeOutcome.SKIPPED,
                did_system_protect=ProtectionAssessment.YES,
                was_rejection_correct=None,
                discipline_rating=10,
                override_attempted=False,
                learning_note=reason,
                system_adjustment_candidate=False,
            )
        )

    def on_trade_confirmed(self, trade: dict) -> None:
        now = datetime.now(UTC)
        pair = str(trade.get("pair", "UNKNOWN"))
        signal_id = str(trade.get("signal_id", ""))
        setup_id = self._setup_by_signal.setdefault(signal_id, f"{pair}_{int(now.timestamp())}")

        direction = str(trade.get("direction", "BUY")).upper()
        journal_router.record_execution(
            ExecutionJournal(
                timestamp=now,
                setup_id=setup_id,
                pair=pair,
                direction=direction,
                entry_price=max(float(trade.get("entry_price", 0.0) or 0.0), 0.00001),
                stop_loss=max(float(trade.get("stop_loss", 0.0) or 0.0), 0.00001),
                take_profit_1=max(float(trade.get("take_profit", 0.0) or 0.0), 0.00001),
                rr_ratio=max(float(trade.get("rr_ratio", 1.0) or 1.0), 0.01),
                risk_percent=max(float(trade.get("total_risk_percent", 1.0) or 1.0), 0.01),
                lot_size=max(float(trade.get("lot_size", 0.01) or 0.01), 0.01),
                execution_mode="TP1_ONLY",
                order_type="PENDING_ONLY",
                sm_state=str(trade.get("status", "PENDING")),
            )
        )

    def on_trade_closed(self, trade: dict, reason: str) -> None:
        now = datetime.now(UTC)
        pair = str(trade.get("pair", "UNKNOWN"))
        signal_id = str(trade.get("signal_id", ""))
        setup_id = self._setup_by_signal.setdefault(signal_id, f"{pair}_{int(now.timestamp())}")

        pnl = float(trade.get("pnl", 0.0) or 0.0)
        if pnl > 0:
            outcome = TradeOutcome.WIN
            protected = ProtectionAssessment.YES
        elif pnl < 0:
            outcome = TradeOutcome.LOSS
            protected = ProtectionAssessment.NO
        else:
            outcome = TradeOutcome.BREAKEVEN
            protected = ProtectionAssessment.UNCLEAR

        journal_router.record_reflection(
            ReflectiveJournal(
                timestamp=now,
                setup_id=setup_id,
                pair=pair,
                outcome=outcome,
                did_system_protect=protected,
                was_rejection_correct=None,
                discipline_rating=8,
                override_attempted=False,
                learning_note=reason,
                system_adjustment_candidate=False,
            )
        )


trade_journal_automation_service = TradeJournalAutomationService()
