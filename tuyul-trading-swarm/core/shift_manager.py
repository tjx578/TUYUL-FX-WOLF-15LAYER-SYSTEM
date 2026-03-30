"""Shift Manager — mengatur rotasi 24/5 coverage untuk semua agent.

Shift Model:
  MONITORING  → market scanner, news agent, market condition agent
  ANALYSIS    → technical structure, smart money, risk-reward
  CONTROL     → orchestrator, psychology, execution control
  REVIEW      → journal, audit, memory handoff

Session Windows (UTC):
  SYDNEY    : 21:00 - 06:00
  TOKYO     : 00:00 - 09:00
  LONDON    : 07:00 - 16:00
  NEW_YORK  : 12:00 - 21:00
  OVERLAP   : 12:00 - 16:00 (London/NY), 07:00 - 09:00 (Tokyo/London)
"""
from __future__ import annotations

import os
from datetime import datetime, time, timezone
from enum import Enum
from typing import Optional

from loguru import logger


class ShiftType(str, Enum):
    MONITORING = "MONITORING"
    ANALYSIS = "ANALYSIS"
    CONTROL = "CONTROL"
    REVIEW = "REVIEW"


class MarketSession(str, Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP_LDN_NY = "OVERLAP_LDN_NY"
    OVERLAP_TOK_LDN = "OVERLAP_TOK_LDN"
    CLOSED = "CLOSED"


SHIFT_AGENTS: dict[ShiftType, list[str]] = {
    ShiftType.MONITORING: [
        "market_scanner",
        "news_event_risk",
        "market_condition",
    ],
    ShiftType.ANALYSIS: [
        "technical_structure",
        "smart_money",
        "risk_reward",
    ],
    ShiftType.CONTROL: [
        "orchestrator",
        "psychology_discipline",
        "trade_execution",
    ],
    ShiftType.REVIEW: [
        "journal_review",
        "audit_governance",
        "memory_handoff",
    ],
}

# UTC hour thresholds
SESSION_WINDOWS: dict[MarketSession, tuple[int, int]] = {
    MarketSession.SYDNEY: (21, 6),
    MarketSession.TOKYO: (0, 9),
    MarketSession.LONDON: (7, 16),
    MarketSession.NEW_YORK: (12, 21),
    MarketSession.OVERLAP_LDN_NY: (12, 16),
    MarketSession.OVERLAP_TOK_LDN: (7, 9),
}


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    """Cek apakah jam dalam range (handle midnight wrap)."""
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


class ShiftManager:
    """Mengelola shift rotation dan deteksi session aktif."""

    def current_utc_hour(self) -> int:
        return datetime.now(timezone.utc).hour

    def current_weekday(self) -> int:
        """Return 0=Mon, 6=Sun."""
        return datetime.now(timezone.utc).weekday()

    def is_market_open(self) -> bool:
        """Pasar forex buka Senin 00:00 - Jumat 21:00 UTC."""
        weekday = self.current_weekday()
        hour = self.current_utc_hour()
        if weekday == 5:  # Sabtu
            return False
        if weekday == 6:  # Minggu
            return hour >= 21  # Sydney buka
        if weekday == 4 and hour >= 21:  # Jumat setelah NY close
            return False
        return True

    def active_session(self) -> MarketSession:
        """Deteksi session pasar yang sedang aktif."""
        if not self.is_market_open():
            return MarketSession.CLOSED
        hour = self.current_utc_hour()
        if _hour_in_range(hour, 12, 16):
            return MarketSession.OVERLAP_LDN_NY
        if _hour_in_range(hour, 7, 9):
            return MarketSession.OVERLAP_TOK_LDN
        if _hour_in_range(hour, 12, 21):
            return MarketSession.NEW_YORK
        if _hour_in_range(hour, 7, 16):
            return MarketSession.LONDON
        if _hour_in_range(hour, 0, 9):
            return MarketSession.TOKYO
        if _hour_in_range(hour, 21, 6):
            return MarketSession.SYDNEY
        return MarketSession.CLOSED

    def active_shift(self) -> ShiftType:
        """Tentukan shift aktif berdasarkan jam UTC."""
        hour = self.current_utc_hour()
        if 0 <= hour < 6:
            return ShiftType.MONITORING    # Asia dead zone
        if 6 <= hour < 12:
            return ShiftType.ANALYSIS     # Pre-London
        if 12 <= hour < 18:
            return ShiftType.CONTROL      # London/NY overlap — prime time
        return ShiftType.REVIEW           # Post-NY, daily wrap

    def active_agents(self) -> list[str]:
        """Daftar agent aktif untuk shift sekarang."""
        shift = self.active_shift()
        return SHIFT_AGENTS[shift]

    def shift_id(self) -> str:
        """ID unik untuk shift ini."""
        now = datetime.now(timezone.utc)
        shift = self.active_shift()
        return f"{now.strftime('%Y%m%d')}_{shift.value}"

    def session_quality(self) -> str:
        """Rating kualitas session untuk trading."""
        session = self.active_session()
        high_quality = {MarketSession.OVERLAP_LDN_NY, MarketSession.LONDON, MarketSession.NEW_YORK}
        medium_quality = {MarketSession.TOKYO, MarketSession.OVERLAP_TOK_LDN}
        if session in high_quality:
            return "HIGH"
        if session in medium_quality:
            return "MEDIUM"
        if session == MarketSession.SYDNEY:
            return "LOW"
        return "CLOSED"

    def is_high_impact_window(self) -> bool:
        """Apakah kita di sekitar open/close session penting?"""
        hour = self.current_utc_hour()
        # London open (7-8 UTC), NY open (12-13 UTC), London close (16-17 UTC)
        high_impact_hours = {7, 8, 12, 13, 16, 17}
        return hour in high_impact_hours

    def status_summary(self) -> dict:
        """Ringkasan status shift dan session untuk handoff."""
        return {
            "utc_time": datetime.now(timezone.utc).isoformat(),
            "market_open": self.is_market_open(),
            "active_session": self.active_session().value,
            "session_quality": self.session_quality(),
            "active_shift": self.active_shift().value,
            "active_agents": self.active_agents(),
            "shift_id": self.shift_id(),
            "high_impact_window": self.is_high_impact_window(),
        }


_shift_manager: ShiftManager | None = None


def get_shift_manager() -> ShiftManager:
    global _shift_manager
    if _shift_manager is None:
        _shift_manager = ShiftManager()
    return _shift_manager
