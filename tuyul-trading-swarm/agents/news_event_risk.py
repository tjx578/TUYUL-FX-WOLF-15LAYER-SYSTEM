"""Agent 7: News & Event Risk — kalender risiko dan window danger zone.

Hard rules:
  - 30 menit sebelum/sesudah high-impact news → REJECT
  - Hari NFP (Jumat pertama setiap bulan) → extra caution
  - Central bank meeting day → REJECT atau WATCHLIST
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


NEWS_BLACKOUT_MINUTES = 30  # Menit sebelum/sesudah high-impact news


class NewsEventRiskAgent(BaseAgent):
    """Monitor kalender risiko dan blokir setup yang terekspos danger window."""

    agent_id = 7
    agent_name = "news_event_risk"
    domain = "environment"
    role = "news-gate"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        ctx = candidate.raw_context
        details: dict[str, Any] = {}
        disqualifiers: list[str] = []
        warnings: list[str] = []

        # ── High-impact events ────────────────────────────────────────────
        upcoming_events: list[dict] = ctx.get("upcoming_news_events", [])
        details["events_checked"] = len(upcoming_events)

        now = datetime.utcnow()
        high_impact_danger = False
        danger_events: list[str] = []

        for event in upcoming_events:
            impact = str(event.get("impact", "LOW")).upper()
            event_name = event.get("name", "Unknown Event")
            event_time_raw = event.get("time", "")

            try:
                if isinstance(event_time_raw, str) and event_time_raw:
                    event_time = datetime.fromisoformat(event_time_raw.replace("Z", "+00:00"))
                    event_time = event_time.replace(tzinfo=None)
                    minutes_to_event = (event_time - now).total_seconds() / 60

                    if impact == "HIGH" and abs(minutes_to_event) <= NEWS_BLACKOUT_MINUTES:
                        high_impact_danger = True
                        danger_events.append(
                            f"{event_name} dalam {minutes_to_event:.0f} menit"
                        )
                    elif impact == "MEDIUM" and 0 < minutes_to_event <= 15:
                        warnings.append(f"Medium-impact event approaching: {event_name}")
            except (ValueError, TypeError) as e:
                logger.debug(f"[NewsAgent] Cannot parse event time: {e}")

        details["high_impact_danger"] = high_impact_danger
        details["danger_events"] = danger_events

        if high_impact_danger:
            disqualifiers.append(
                f"Dalam danger window high-impact news: {', '.join(danger_events)}"
            )

        # ── Risk level dari context ────────────────────────────────────────
        news_risk_level = str(ctx.get("news_risk_level", "UNKNOWN")).upper()
        details["risk_level"] = news_risk_level

        if news_risk_level == "HIGH" and not high_impact_danger:
            disqualifiers.append("News risk level HIGH — lingkungan berbahaya untuk eksekusi")
        elif news_risk_level == "MEDIUM":
            warnings.append("News risk level MEDIUM — waspada dan monitor news feed")

        # ── NFP / Central bank flag ───────────────────────────────────────
        is_nfp_day = ctx.get("is_nfp_day", False)
        is_central_bank_day = ctx.get("is_central_bank_meeting_day", False)
        details["is_nfp_day"] = is_nfp_day
        details["is_central_bank_day"] = is_central_bank_day

        if is_nfp_day:
            # NFP hari: hanya valid sebelum 12:00 UTC atau setelah 14:00 UTC
            current_hour = now.hour
            if 12 <= current_hour < 14:
                disqualifiers.append("NFP danger window (12:00-14:00 UTC) — trading diblokir")
            else:
                warnings.append("NFP hari ini — waspada untuk semua USD pair")

        if is_central_bank_day:
            disqualifiers.append(
                "Central bank meeting hari ini — kondisi tidak dapat diprediksi"
            )

        # ── Determine final risk level ────────────────────────────────────
        if disqualifiers:
            final_risk = "HIGH"
        elif warnings:
            final_risk = "MEDIUM"
        else:
            final_risk = "LOW"

        details["risk_level"] = final_risk

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"News/event risk tidak dapat diterima: {final_risk}",
                disqualifiers=disqualifiers,
                details=details,
            )

        return self.pass_report(
            candidate,
            reason=f"News risk {final_risk} — aman untuk eksekusi",
            score=100.0 if final_risk == "LOW" else 75.0,
            details=details,
            warnings=warnings,
        )
