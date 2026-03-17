"""
Backward-compatibility shim — all logic moved to analysis/tick_pipeline.py.

This file exists ONLY so that existing ``from analysis.candle_builder import …``
statements keep working. New code should import from ``analysis.tick_pipeline``
or directly from ``ingest.candle_builder``.
"""

from analysis.tick_pipeline import *  # noqa: F401, F403

# Re-export CandleBuilder alias (some tests import it as CandleBuilder)
try:  # noqa: SIM105
    from ingest.candle_builder import CandleBuilder  # noqa: F401
except ImportError:
    pass
