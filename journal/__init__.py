"""
Journal zone — Append-only audit & reflective layers.
NO decision authority. NO execution side-effects.

L13: Post-trade reflection (J4)
L14: Adaptive learning / pattern memory (advisory-only)
L15: System health & meta-governance (monitoring-only)

Re-exports:
    JournalSchema models  → journal.journal_schema
    JournalRouter         → journal.journal_router
    JournalWriter         → journal.journal_writer
    JournalMetrics        → journal.journal_metrics
    JournalGPTBridge      → journal.journal_gpt_bridge
    L13 Reflection        → journal.l13_reflection
    L14 Adaptive          → journal.l14_adaptive
    L15 Health            → journal.l15_health
"""

# ── Schema models (J1-J4) ────────────────────────────────────────────────────
from journal.journal_schema import (  # noqa: F401
    ContextJournal,
    DecisionJournal,
    ExecutionJournal,
    ReflectiveJournal,
    VerdictType,
    TradeOutcome,
    ProtectionAssessment,
)

# ── Core components ───────────────────────────────────────────────────────────
from journal.journal_writer import JournalWriter  # noqa: F401
from journal.journal_router import JournalRouter, journal_router  # noqa: F401
from journal.journal_metrics import get_daily_stats, get_weekly_stats, get_rejection_accuracy  # noqa: F401
from journal.journal_gpt_bridge import compute_metrics, export_for_gpt  # noqa: F401

# ── Layer modules ─────────────────────────────────────────────────────────────
from journal.l13_reflection import reflect, L13ReflectionRecord  # noqa: F401
from journal.l14_adaptive import analyze_patterns, L14AdaptiveResult  # noqa: F401
from journal.l15_health import check_health, L15HealthReport  # noqa: F401
