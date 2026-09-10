"""
L4 — Scoring Engine
"""

from config.constants import get_threshold

# Wolf 30-Point thresholds
WOLF_MAX_SCORE: int = get_threshold("wolf_30_point.max_score", 30)
WOLF_MIN_SCORE: int = get_threshold("wolf_30_point.min_score", 22)
TECH_MIN: int = get_threshold("wolf_30_point.sub_thresholds.technical_min", 9)
FTA_MIN: int = get_threshold("wolf_30_point.sub_thresholds.fta_min", 3)
EXEC_MIN: int = get_threshold("wolf_30_point.sub_thresholds.execution_min", 4)


class L4ScoringEngine:
    def score(self, l1: dict, l2: dict, l3: dict) -> dict:
        score = 0

        if l1.get("valid") and not l1.get("news_lock"):
            score += 30

        if l2.get("aligned"):
            score += 30

        if l3.get("valid"):
            score += 40

        return {
            "technical_score": score,
            "max_score": 100,
            "valid": True,
        }


# Placeholder
