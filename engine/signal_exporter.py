"""Signal exporter placeholder for engine-to-allocation handoff."""

from allocation.signal_registry import SignalRegistry


def export_signal(signal: dict) -> None:
    """Publish an engine signal into the global registry."""
    SignalRegistry().publish(signal)
