"""Re-export L7/L8 minimal analyzers from core for architecture-consistent import path.

The canonical implementation lives at ``core.L7_L8_minimal``. This module
provides the ``analysis.layers`` namespace path specified in the Integration
Guide so that the pipeline and any external code can import from either location.

Zone: analysis/layers/ -- read-only re-export shim, no execution side-effects.
"""

from core.L7_L8_minimal import *  # noqa: F401,F403
from core.L7_L8_minimal import __all__ as _all  # noqa: F401

__all__ = list(_all)
