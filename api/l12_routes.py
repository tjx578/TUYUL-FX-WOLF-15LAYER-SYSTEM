from fastapi import APIRouter, HTTPException

from context.live_context_bus import LiveContextBus
from execution.state_machine import ExecutionStateMachine
from storage.l12_cache import get_verdict
from utils.timezone_utils import format_local, format_utc, now_utc

router = APIRouter()

# Available currency pairs (can be loaded from config)
AVAILABLE_PAIRS = [
    {"symbol": "EURUSD", "name": "Euro/US Dollar", "enabled": True},
    {"symbol": "GBPUSD", "name": "British Pound/US Dollar", "enabled": True},
    {"symbol": "USDJPY", "name": "US Dollar/Japanese Yen", "enabled": True},
    {"symbol": "AUDUSD", "name": "Australian Dollar/US Dollar", "enabled": True},
    {"symbol": "USDCAD", "name": "US Dollar/Canadian Dollar", "enabled": True},
]


@router.get("/api/v1/l12/{pair}")
def fetch_l12(pair: str):
    """Get L12 verdict for a specific pair with timezone info."""
    data = get_verdict(pair.upper())
    if not data:
        raise HTTPException(status_code=404, detail=f"No verdict found for {pair}")

    # Add dual timezone info if timestamp exists
    if "timestamp" in data:
        try:
            current_time = now_utc()
            data["time_utc"] = format_utc(current_time)
            data["time_local"] = format_local(current_time)
        except Exception:
            pass

    return data


@router.get("/api/v1/verdict/all")
def fetch_all_verdicts():
    """Get verdicts for all available pairs."""
    verdicts = {}
    for pair_info in AVAILABLE_PAIRS:
        pair = pair_info["symbol"]
        data = get_verdict(pair)
        if data:
            verdicts[pair] = data

    return verdicts


@router.get("/api/v1/context")
def fetch_context():
    """Get live context snapshot."""
    context_bus = LiveContextBus()
    snapshot = context_bus.snapshot()

    # Add timestamp info
    current_time = now_utc()
    snapshot["timestamp_utc"] = format_utc(current_time)
    snapshot["timestamp_local"] = format_local(current_time)

    return snapshot


@router.get("/api/v1/execution")
def fetch_execution():
    """Get current execution state."""
    state_machine = ExecutionStateMachine()
    execution_state = state_machine.snapshot()

    # Add timezone info
    current_time = now_utc()
    execution_state["current_time_utc"] = format_utc(current_time)
    execution_state["current_time_local"] = format_local(current_time)

    return execution_state


@router.get("/api/v1/pairs")
def fetch_pairs():
    """Get list of available currency pairs."""
    return AVAILABLE_PAIRS
