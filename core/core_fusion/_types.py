"""
Fusion Types -- Exceptions, Enums, Constants, Dataclasses.
Shared type definitions for all fusion sub-modules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Final

# ── Exceptions ────────────────────────────────────────────────────────────────


class FusionError(Exception):
    """Base exception for all fusion module errors."""


class FusionComputeError(FusionError):
    """Raised when fusion computation fails."""


class FusionInputError(FusionError):
    """Raised when fusion input validation fails."""


class FusionConfigError(FusionError):
    """Raised when fusion configuration is invalid."""


# ── Enumerations ──────────────────────────────────────────────────────────────


class FusionBiasMode(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class FusionState(Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class MomentumBand(Enum):
    HYPER = "hyper"
    STRONG = "strong"
    BALANCED = "balanced"
    CALM = "calm"


class DivergenceType(Enum):
    REGULAR_BULLISH = "regular_bullish"
    REGULAR_BEARISH = "regular_bearish"
    HIDDEN_BULLISH = "hidden_bullish"
    HIDDEN_BEARISH = "hidden_bearish"
    NONE = "none"


class DivergenceStrength(Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class FusionAction(Enum):
    EXECUTE = "EXECUTE"
    MONITOR = "MONITOR"
    WAIT = "WAIT"


class MarketState(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class TransitionState(Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    WEAK_BULLISH = "WEAK_BULLISH"
    NEUTRAL = "NEUTRAL"
    WEAK_BEARISH = "WEAK_BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class LiquidityType(Enum):
    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"


class LiquidityStatus(Enum):
    UNTAPPED = "untapped"
    PARTIALLY_SWEPT = "partially_swept"
    FULLY_SWEPT = "swept"


class ResonanceState(Enum):
    EXPANSION_RESONANCE = "Expansion Resonance"
    EQUILIBRIUM_RESONANCE = "Equilibrium Resonance"
    ADAPTIVE_COMPRESSION = "Adaptive Compression"
    PHASE_DRIFT_DETECTED = "Phase Drift Detected"


class VolumeZoneType(Enum):
    HIGH_VOLUME_NODE = "hvn"
    LOW_VOLUME_NODE = "lvn"
    POC = "poc"
    VAH = "vah"
    VAL = "val"


class VolatilityRegime(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_EMA_FAST: Final[int] = 21
DEFAULT_EMA_SLOW: Final[int] = 50
DEFAULT_PRECISION_WEIGHT_MIN: Final[float] = 0.70
DEFAULT_PRECISION_WEIGHT_MAX: Final[float] = 1.30
DEFAULT_META_DRIFT_FREEZE: Final[float] = 0.006
DEFAULT_MIN_INTEGRITY: Final[float] = 0.96
DEFAULT_LOOKBACK_BARS: Final[int] = 50
DEFAULT_MIN_BARS_APART: Final[int] = 5
DEFAULT_MAX_BARS_APART: Final[int] = 30
DEFAULT_MIN_CONFLUENCE: Final[int] = 2
DEFAULT_MC_SIMULATIONS: Final[int] = 5000
DEFAULT_MC_MIN_SIMULATIONS: Final[int] = 500
DEFAULT_FTTC_ITERATIONS: Final[int] = 50000
DEFAULT_FTTC_HORIZON_DAYS: Final[int] = 180
DEFAULT_FTTC_CONFIDENCE: Final[float] = 0.95
MTF_TIMEFRAMES: Final[tuple[str, ...]] = ("H1", "H4", "D1", "W1")
DEFAULT_SWING_LOOKBACK: Final[int] = 20
DEFAULT_EQUAL_LEVEL_TOLERANCE: Final[float] = 0.0005


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class FieldContext:
    pair: str
    timeframe: str
    field_state: str
    coherence: float
    resonance: float
    phase: str
    timestamp: str
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    lambda_esi: float = 0.06
    field_integrity: float = 0.95

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FusionPrecisionResult:
    timestamp: str
    fusion_strength: float
    bias_mode: str
    precision_weight: float
    precision_confidence_hint: float
    details: dict[str, Any]
    symbol: str | None = None
    pair: str | None = None
    trade_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EquilibriumResult:
    timestamp: str
    price_momentum: float
    volume_factor: float
    time_factor: float
    equilibrium: float
    imbalance: float
    fusion_score: float
    fusion_score_signed: float
    reflective_confidence: float
    bias: str
    state: str
    momentum_band: str
    status: str = "ok"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DivergenceSignal:
    indicator: str
    divergence_type: DivergenceType
    strength: DivergenceStrength
    price_start: float
    price_end: float
    indicator_start: float
    indicator_end: float
    bars_apart: int
    confidence: float


@dataclass
class MultiDivergenceResult:
    timestamp: datetime
    pair: str
    timeframe: str
    rsi_divergence: DivergenceSignal | None
    macd_divergence: DivergenceSignal | None
    cci_divergence: DivergenceSignal | None
    mfi_divergence: DivergenceSignal | None
    confluence_count: int
    overall_signal: DivergenceType
    overall_strength: DivergenceStrength
    confidence: float


@dataclass
class AdaptiveUpdate:
    timestamp: str
    meta_drift: float
    integrity_index: float
    mean_energy: float
    freeze_thresholds: bool
    reason: str
    proposed: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfidenceLineage:
    raw: float
    weighted: float
    final: float
    precision_weight: float
    gate_threshold: float
    gate_pass: bool
    authority: str
    notes: str
    lambda_esi: float = 0.06
    field_state: str | None = None
    field_integrity: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MonteCarloResult:
    conf12_raw: float
    reliability_score: float
    stability_index: float
    total_simulations: int
    bias_mean: float
    volatility_mean: float
    reflective_integrity: float
    timestamp: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FTTCConfig:
    iterations: int = DEFAULT_FTTC_ITERATIONS
    horizon_days: int = DEFAULT_FTTC_HORIZON_DAYS
    confidence_threshold: float = DEFAULT_FTTC_CONFIDENCE
    min_frpc: float = 0.96
    min_tii: float = 0.92
    target_drift: float = 0.004
    alpha: float = 0.45
    beta: float = 0.35
    gamma: float = 0.20


@dataclass
class FTTCResult:
    win_probability: float
    expected_return: float
    max_drawdown_probability: float
    optimal_position_size: float
    confidence_interval: tuple[float, float]
    transition_probabilities: dict[str, float]
    escape_rates: dict[str, float]
    meta_drift: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QMatrixConfig:
    base_transition_rate: float = 0.1
    volatility_sensitivity: float = 0.5
    trend_sensitivity: float = 0.3
    momentum_sensitivity: float = 0.2
    regularization: float = 0.01


@dataclass
class LiquidityZone:
    zone_type: LiquidityType
    status: LiquidityStatus
    price_level: float
    price_range: tuple[float, float]
    strength: float
    touch_count: int
    created_at: datetime
    last_tested: datetime | None
    timeframe: str


@dataclass
class LiquidityMapResult:
    timestamp: datetime
    pair: str
    buy_side_zones: list[LiquidityZone]
    sell_side_zones: list[LiquidityZone]
    nearest_buy_liquidity: float | None
    nearest_sell_liquidity: float | None
    liquidity_imbalance: float


@dataclass
class CoherenceAudit:
    timestamp: str
    lookback: int
    reflective_coherence: float
    divergence_window: bool
    divergence_alert: str
    stability_state: str
    gate_threshold: float
    gate_pass: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VolumeProfileResult:
    timestamp: datetime
    pair: str
    timeframe: str
    poc_price: float
    vah_price: float
    val_price: float
    value_area_percent: float
    volume_nodes: list[dict[str, Any]]
    total_volume: float
    profile_shape: str


@dataclass
class VolumeZone:
    zone_type: VolumeZoneType
    price_low: float
    price_high: float
    volume: float
    relative_strength: float


@dataclass
class CounterZoneContext:
    price: float
    vwap: float
    atr: float
    rsi: float
    mfi: float
    cci50: float
    rsi_h4: float
    trq_energy: float = 1.0
    reflective_intensity: float = 1.0
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    integrity_index: float = 0.97
    journal_path: Any = None
    symbol: str | None = None
    pair: str | None = None
    trade_id: str | None = None


@dataclass
class NormalizedMicro:
    twms_micro: float
    vol_penalty: float
    regime: VolatilityRegime
    confidence_multiplier: float
    is_valid: bool
    conflict_detected: bool
    raw_twms_micro: float
    raw_volatility: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "twms_micro": self.twms_micro,
            "vol_penalty": self.vol_penalty,
            "regime": self.regime.value,
            "confidence_multiplier": self.confidence_multiplier,
            "is_valid": self.is_valid,
            "conflict_detected": self.conflict_detected,
            "raw_twms_micro": self.raw_twms_micro,
            "raw_volatility": self.raw_volatility,
        }


class MicroBounds:
    def __init__(
        self, twms_max: float = 0.30, twms_min: float = -0.30, vol_cap: float = 0.50, min_confidence: float = 0.70
    ) -> None:
        self.twms_max = twms_max
        self.twms_min = twms_min
        self.vol_cap = vol_cap
        self.min_confidence = min_confidence
