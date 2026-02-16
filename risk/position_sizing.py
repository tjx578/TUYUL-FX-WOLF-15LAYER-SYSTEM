class PositionSizingResult:
    def __init__(self, lot_size: float):
        self.lot_size = lot_size

    @property
    def position_size(self) -> float:
        """Alias for lot_size for backward compatibility."""
        return self.lot_size
