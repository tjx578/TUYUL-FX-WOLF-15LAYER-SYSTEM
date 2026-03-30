"""Decision packet schema — output final dari orchestrator setelah semua agent evaluate."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.agent_report import AgentReport
from schemas.trade_candidate import FinalVerdict, TradeCandidate


class WatchlistEntry(BaseModel):
    """Entry dalam watchlist — setup yang belum matang."""

    candidate_id: str
    instrument: str
    direction: str
    wait_reason: str
    invalidation_trigger: str
    recheck_condition: str
    expiration_condition: str
    next_review_time: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionPacket(BaseModel):
    """Paket eksekusi yang siap dikirim ke broker setelah semua gate lulus."""

    candidate_id: str
    instrument: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    pip_risk: float
    pip_reward: float
    rr_ratio: float
    session: str
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    execution_note: str = ""


class DecisionPacket(BaseModel):
    """Paket keputusan final yang diproduksi oleh orchestrator."""

    packet_id: str
    candidate_id: str
    instrument: str
    direction: str
    session: str
    market_state: str

    # Gate assessments
    technical_score: str = Field(default="N/A", description="e.g. 11/12")
    smart_money_confidence: str = Field(default="N/A", description="e.g. 85%")
    rr_ratio: str = Field(default="N/A", description="e.g. 1:2.5")
    news_risk: str = Field(default="N/A", description="LOW | MEDIUM | HIGH")
    discipline_state: str = Field(default="N/A", description="READY | CAUTION | HALT")

    # Verdict
    final_verdict: FinalVerdict
    decision_reason: str
    next_action: str = ""
    audit_note: str = ""
    journal_summary: str = ""

    # Agent reports
    agent_reports: list[AgentReport] = Field(default_factory=list)
    failed_gates: list[str] = Field(default_factory=list)
    disqualifiers: list[str] = Field(default_factory=list)

    # Optional sub-objects
    watchlist_entry: Optional[WatchlistEntry] = None
    execution_packet: Optional[ExecutionPacket] = None

    decided_at: datetime = Field(default_factory=datetime.utcnow)
    shift: str = Field(default="", description="Shift aktif saat keputusan")
    cycle_ms: Optional[float] = Field(default=None, description="Total durasi siklus evaluasi")

    model_config = ConfigDict(use_enum_values=True)
