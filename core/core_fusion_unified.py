"""Backward-compatibility shim: core_fusion_unified -> core.core_fusion package.

The original monolith core_fusion_unified.py (5,330 LOC) was refactored into
the core/core_fusion/ package (20 sub-modules). This shim ensures any legacy
imports like ``from core.core_fusion_unified import FusionIntegrator`` still
work without modification.

Zone: core/ -- compatibility shim only, no execution side-effects.
"""

from .core_fusion import *  # noqa: F401,F403
from .core_fusion import __all__ as __all__
