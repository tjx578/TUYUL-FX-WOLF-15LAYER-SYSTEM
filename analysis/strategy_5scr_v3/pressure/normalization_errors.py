"""Typed failures for the inert pressure-emission adapters."""


class PressureEmissionNormalizationError(ValueError):
    """The source cannot be represented honestly as a pressure emission."""


__all__ = ["PressureEmissionNormalizationError"]
