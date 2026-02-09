"""
News Rules
Defines lock windows based on impact level.
"""

NEWS_RULES = {
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
}
