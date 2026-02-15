from dataclasses import dataclass


@dataclass
class PositionSizingResult:
    # ...existing code...
    final_fraction: float
    risk_percent: float
    # ...existing code...

    # ------------------------------------------------------------
    # Backward Compatibility Properties
    # risk_engine_v2 and dashboard read these aliases.
    # ------------------------------------------------------------

    @property
    def risk_multiplier(self) -> float:
        """Alias for final_fraction (legacy contract)."""
        return self.final_fraction

@property
def position_size(self) -> float:
    """Alias for risk_percent (legacy contract)."""
    return self.risk_percent
