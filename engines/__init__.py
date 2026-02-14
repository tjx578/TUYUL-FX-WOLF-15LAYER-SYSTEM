"""Engine facade package for TUYUL FX system."""

from .fusion_precision_engine import FusionPrecision, FusionPrecisionEngine


def create_engine_suite():
    """Create a minimal engine suite map."""
    return {
        "precision": FusionPrecisionEngine(),
    }


__all__ = ["FusionPrecision", "FusionPrecisionEngine", "create_engine_suite"]
