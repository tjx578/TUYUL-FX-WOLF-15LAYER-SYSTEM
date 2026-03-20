"""
News sentiment analysis sub-package.

Provides FinBERT-based and keyword-based sentiment scoring
with entity recognition for central banks and currencies.

All outputs are advisory-only — no execution authority.
"""

from news.sentiment.sentiment_engine import (
    SentimentResult,
    SentimentScorer,
    get_default_scorer,
)

__all__ = [
    "SentimentResult",
    "SentimentScorer",
    "get_default_scorer",
]
