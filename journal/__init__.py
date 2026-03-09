"""
Journal zone — Append-only audit & reflective layers.
NO decision authority. NO execution side-effects.

L13: Post-trade reflection (J4)
L14: Adaptive learning / pattern memory (advisory-only)
L15: System health & meta-governance (monitoring-only)

Re-exports:
    JournalSchema models  -> journal.journal_schema
    JournalRouter         -> journal.journal_router
    JournalWriter         -> journal.journal_writer
    JournalMetrics        -> journal.journal_metrics
    JournalGPTBridge      -> journal.journal_gpt_bridge
    L13 Reflection        -> journal.l13_reflection
    L14 Adaptive          -> journal.l14_adaptive
    L15 Health            -> journal.l15_health
"""

__all__ = [
    "compute_metrics",
    "export_for_gpt",
    "get_daily_stats",
    "get_rejection_accuracy",
    "get_weekly_stats",
    "JournalRepository",
    "JournalRouter",
    "journal_router",
    "ContextJournal",
    "DecisionJournal",
    "ExecutionJournal",
    "ProtectionAssessment",
    "ReflectiveJournal",
    "TradeOutcome",
    "VerdictType",
    "JournalWriter",
    "L13ReflectionRecord",
    "reflect",
    "L14AdaptiveResult",
    "analyze_patterns",
    "L14AdaptiveReflection",
    "analyze_underperforming_setups",
    "L15HealthReport",
    "check_health",
]

# ── Schema models (J1-J4) ────────────────────────────────────────────────────
from journal.journal_gpt_bridge import compute_metrics, export_for_gpt  # noqa: F401
from journal.journal_metrics import get_daily_stats, get_rejection_accuracy, get_weekly_stats  # noqa: F401
from journal.journal_repository import JournalRepository  # noqa: F401
from journal.journal_router import JournalRouter, journal_router  # noqa: F401
from journal.journal_schema import (  # noqa: F401
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ProtectionAssessment,
    ReflectiveJournal,
    TradeOutcome,
    VerdictType,
)

# ── Core components ───────────────────────────────────────────────────────────
from journal.journal_writer import JournalWriter  # noqa: F401

# ── Layer modules ─────────────────────────────────────────────────────────────
from journal.l13_reflection import L13ReflectionRecord, reflect  # noqa: F401
from journal.l14_adaptive import L14AdaptiveResult, analyze_patterns  # noqa: F401
from journal.l14_underperform_miner import (  # noqa: F401
    L14AdaptiveReflection,
    analyze_underperforming_setups,
)
from journal.l15_health import L15HealthReport, check_health  # noqa: F401
