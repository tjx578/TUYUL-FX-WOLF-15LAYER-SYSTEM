class PositionSizingResult:
    """Result of position sizing calculation."""

    def __init__(
        self,
        lot_size: float = 0.0,
        risk_amount: float = 0.0,
        risk_percent: float = 0.0,
        stop_loss_pips: float = 0.0,
        pip_value: float = 0.0,
        margin_required: float = 0.0,
        max_safe_lot: float = 0.0,
    ):
        self.lot_size = lot_size
        self.risk_amount = risk_amount
        self.risk_percent = risk_percent
        self.stop_loss_pips = stop_loss_pips
        self.pip_value = pip_value
        self.margin_required = margin_required
        self.max_safe_lot = max_safe_lot

    @property
    def position_size(self) -> float:
        """Alias for lot_size for backward compatibility."""
        return self.lot_size

    def to_dict(self) -> dict:
        return {
            "lot_size": self.lot_size,
            "position_size": self.position_size,
            "risk_amount": self.risk_amount,
            "risk_percent": self.risk_percent,
            "stop_loss_pips": self.stop_loss_pips,
            "pip_value": self.pip_value,
            "margin_required": self.margin_required,
            "max_safe_lot": self.max_safe_lot,
        }
