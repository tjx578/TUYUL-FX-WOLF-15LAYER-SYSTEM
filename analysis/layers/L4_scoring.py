"""
L4 — Scoring Engine
"""


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
