"""
Pipeline Result v7.4r∞ -- Structured output dataclass.

Replaces the old SovereignResult and provides typed access
to all pipeline outputs while maintaining dict backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineResult:
    """
    Structured result from the Wolf Constitutional Pipeline.

    Provides typed fields for all pipeline outputs.
    Use .to_dict() for backward-compatible dict output.
    """

    schema: str
    pair: str
    timestamp: str
    synthesis: dict[str, Any]
    l12_verdict: dict[str, Any]
    reflective_pass1: dict[str, Any] | None = None
    reflective_pass2: dict[str, Any] | None = None
    l15_meta: dict[str, Any] | None = None
    l14_json: dict[str, Any] | None = None
    sovereignty: dict[str, Any] = field(default_factory=dict)
    enforcement: dict[str, Any] | None = None
    execution_map: dict[str, Any] | None = None
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    # ── Backward-compatible dict access ──

    @property
    def reflective(self) -> dict[str, Any] | None:
        """Backward compat: return best available reflective pass."""
        return self.reflective_pass2 or self.reflective_pass1

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to backward-compatible dict format.

        This matches the original WolfConstitutionalPipeline output shape
        so existing code (main.py, API routes, tests) continues to work.
        """
        return {
            "schema": self.schema,
            "pair": self.pair,
            "timestamp": self.timestamp,
            "synthesis": self.synthesis,
            "l12_verdict": self.l12_verdict,
            "reflective": self.reflective,
            "reflective_pass1": self.reflective_pass1,
            "reflective_pass2": self.reflective_pass2,
            "l14_json": self.l14_json,
            "l15_meta": self.l15_meta,
            "sovereignty": self.sovereignty,
            "enforcement": self.enforcement,
            "execution_map": self.execution_map,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }

    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access for backward compatibility."""
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator for backward compatibility."""
        return key in self.to_dict()

    def get(self, key: str, default: Any = None) -> Any:
        """Allow .get() for backward compatibility."""
        return self.to_dict().get(key, default)
