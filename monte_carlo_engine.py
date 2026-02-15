@dataclass
class MonteCarloResult:
    # ...existing code...
    win_probability: float
    profit_factor: float
    passed_threshold: bool
    # ...existing code...

    # ------------------------------------------------------------
    # Backward Compatibility Alias
    # risk_engine_v2 checks .passed instead of .passed_threshold
    # ------------------------------------------------------------

    @property
    def passed(self) -> bool:
        """Alias for passed_threshold (legacy contract)."""
        return self.passed_threshold