"""
Data structures for Wolf 15-Layer Reasoning Engine
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LayerState(Enum):
    """State untuk setiap layer"""

    PENDING = "pending"
    PROCESSING = "processing"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(Enum):
    """Final verdict options"""

    EXECUTE_BUY = "EXECUTE_BUY"
    EXECUTE_SELL = "EXECUTE_SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class WolfStatus(Enum):
    """Wolf hunt classification"""

    ALPHA_HUNT = "ALPHA_HUNT"  # 30/30 Perfect
    PACK_HUNT = "PACK_HUNT"  # 27-29 Excellent
    SCOUT = "SCOUT"  # 24-26 Good (threshold ≥22 for layer-level, ≥24 for SCOUT)
    NO_HUNT = "NO_HUNT"  # <22 Fail


@dataclass
class WolfContext:
    """Context yang dibawa antar layer"""

    pair: str = ""
    timestamp: str = ""
    current_price: float = 0.0

    # Layer outputs
    layer_states: dict[str, LayerState] = field(default_factory=dict)
    layer_outputs: dict[str, dict] = field(default_factory=dict)

    # Scores
    f_score: int = 0
    t_score: int = 0
    fta_score: float = 0.0
    fta_score_int: int = 0  # 0-4 integer mapping for L10 compatibility
    wolf_30_score: int = 0
    psychology_score: int = 0

    # Thresholds & Gates
    gates_passed: int = 0
    total_gates: int = 9

    # Final decision variables
    verdict: Verdict | None = None
    wolf_status: WolfStatus | None = None
    confidence: str = ""

    # Execution parameters (TP1 ONLY)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    lot_size: float = 0.0
    rr_ratio: float = 0.0


@dataclass
class LayerResult:
    """Result dari setiap layer processing"""

    layer_name: str
    state: LayerState
    score: float
    passed_threshold: bool
    details: dict[str, Any]
    proceed_to_next: bool
    error_message: str = ""
