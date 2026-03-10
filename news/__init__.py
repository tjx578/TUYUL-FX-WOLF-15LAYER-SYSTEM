"""
News package — news/calendar ingestion and blocker subsystem.

Public surface
--------------
NewsEngine         : Legacy synchronous lock check (pipeline-compatible).
NewsService        : Full async service layer (API layer).
BlockerEngine      : Core blocker evaluation logic.
BlockerStatus      : Rich result of a blocker evaluation.
EconomicEvent      : Canonical event model.
ImpactLevel        : Impact level enum.
NEWS_RULES         : Lock window rules by impact level.
"""

from news.blocker_engine import BlockerEngine
from news.models import BlockerStatus, CalendarDaySnapshot, EconomicEvent, ImpactLevel
from news.news_engine import NewsEngine
from news.news_rules import NEWS_RULES
from news.services.news_service import NewsService

__all__ = [
    "BlockerEngine",
    "BlockerStatus",
    "CalendarDaySnapshot",
    "EconomicEvent",
    "ImpactLevel",
    "NEWS_RULES",
    "NewsEngine",
    "NewsService",
]

