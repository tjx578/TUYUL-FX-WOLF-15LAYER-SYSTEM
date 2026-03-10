"""
News Rules
Defines lock windows based on impact level.

Used by both the legacy NewsEngine (backward-compat) and the new
BlockerEngine.  Each rule specifies:

  pre_minutes  : Minutes before an event to begin the lock window.
  post_minutes : Minutes after an event during which the lock remains.
  lock         : Whether this impact level triggers a trading lock at all.
"""

from __future__ import annotations

from typing import TypedDict


class NewsRule(TypedDict):
    pre_minutes: int
    post_minutes: int
    lock: bool


NEWS_RULES: dict[str, NewsRule] = {
    "HIGH": {
        "pre_minutes": 30,
        "post_minutes": 15,
        "lock": True,
    },
    "MEDIUM": {
        "pre_minutes": 15,
        "post_minutes": 10,
        "lock": True,
    },
    "LOW": {
        "pre_minutes": 0,
        "post_minutes": 0,
        "lock": False,
    },
    "HOLIDAY": {
        "pre_minutes": 0,
        "post_minutes": 0,
        "lock": False,
    },
    "UNKNOWN": {
        "pre_minutes": 0,
        "post_minutes": 0,
        "lock": False,
    },
}
