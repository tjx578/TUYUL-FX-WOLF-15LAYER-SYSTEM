"""
News package — news/calendar ingestion, blocker subsystem, and sentiment analysis.

Public surface
--------------
NewsEngine         : Legacy synchronous lock check + sentiment advisory (pipeline-compatible).
NewsService        : Full async service layer (API layer).
BlockerEngine      : Core blocker evaluation logic.
BlockerStatus      : Rich result of a blocker evaluation.
EconomicEvent      : Canonical event model.
ImpactLevel        : Impact level enum.
NEWS_RULES         : Lock window rules by impact level.
SentimentScorer    : Sentiment scoring protocol.
SentimentAggregator: Multi-article sentiment aggregation.
"""

from news.blocker_engine import BlockerEngine
from news.models import BlockerStatus, CalendarDaySnapshot, EconomicEvent, ImpactLevel
from news.news_engine import NewsEngine
from news.news_rules import NEWS_RULES
from news.sentiment.aggregator import SentimentAggregator
from news.sentiment.sentiment_engine import SentimentScorer, get_default_scorer
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
    "SentimentAggregator",
    "SentimentScorer",
    "get_default_scorer",
]
