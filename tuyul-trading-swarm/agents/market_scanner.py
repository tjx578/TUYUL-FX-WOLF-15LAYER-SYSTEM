"""Agent 2: Market Scanner — continuously scan dan filter noise dari kandidat setup."""
from __future__ import annotations

from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


class MarketScannerAgent(BaseAgent):
    """Scan instrumen, session, dan struktur pasar — filter noise sebelum analisis mendalam."""

    agent_id = 2
    agent_name = "market_scanner"
    domain = "scanning"
    role = "pre-filter"

    # Minimum pip untuk pair dianggap aktif
    MIN_SPREAD_PIPS: dict[str, float] = {
        "EURUSD": 0.5, "GBPUSD": 0.8, "USDJPY": 0.5,
        "XAUUSD": 3.0, "US30": 5.0, "GBPJPY": 1.5,
        "AUDUSD": 0.7, "USDCHF": 0.7, "NZDUSD": 0.9,
    }

    # Pair yang diizinkan dalam sistem
    ALLOWED_INSTRUMENTS = {
        "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "US30",
        "GBPJPY", "AUDUSD", "USDCHF", "NZDUSD", "EURJPY",
        "USDCAD", "EURGBP",
    }

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        disqualifiers: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        # ── Cek instrumen valid ────────────────────────────────────────────
        instrument = candidate.instrument.upper()
        if instrument not in self.ALLOWED_INSTRUMENTS:
            disqualifiers.append(f"Instrumen {instrument} tidak ada dalam allowlist")

        details["instrument"] = instrument
        details["allowed"] = instrument in self.ALLOWED_INSTRUMENTS

        # ── Cek session quality dari raw_context ──────────────────────────
        session_quality = candidate.raw_context.get("session_quality", "UNKNOWN")
        details["session_quality"] = session_quality
        if session_quality == "CLOSED":
            disqualifiers.append("Pasar tutup — tidak ada trading")
        elif session_quality == "LOW":
            warnings.append("Session kualitas rendah (Sydney only) — likuiditas tipis")

        # ── Cek pip range minimum ──────────────────────────────────────────
        pip_range = candidate.raw_context.get("daily_pip_range", 0)
        details["daily_pip_range"] = pip_range
        min_range = 30 if "JPY" in instrument or "GOLD" in instrument or "XAU" in instrument else 20
        if pip_range > 0 and pip_range < min_range:
            warnings.append(f"Range harian terlalu kecil: {pip_range} pip (minimum {min_range})")

        # ── Cek spread ────────────────────────────────────────────────────
        spread = candidate.raw_context.get("spread_pips", 0)
        max_spread = self.MIN_SPREAD_PIPS.get(instrument, 1.5) * 3
        details["spread_pips"] = spread
        if spread > max_spread and spread > 0:
            disqualifiers.append(f"Spread terlalu lebar: {spread} pip (max {max_spread})")

        # ── Cek pip risk masuk akal ────────────────────────────────────────
        pip_risk = candidate.pip_risk()
        details["pip_risk"] = round(pip_risk, 1)
        if pip_risk < 5:
            disqualifiers.append(f"SL terlalu dekat: {pip_risk:.1f} pip (minimum 5 pip)")
        if pip_risk > 200:
            disqualifiers.append(f"SL terlalu jauh: {pip_risk:.1f} pip (maximum 200 pip)")

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"Scanner reject: {'; '.join(disqualifiers)}",
                disqualifiers=disqualifiers,
                details=details,
            )

        return self.pass_report(
            candidate,
            reason=f"Kandidat lolos scanner — {instrument} valid untuk evaluasi lanjutan",
            score=85.0,
            details=details,
            warnings=warnings,
        )
