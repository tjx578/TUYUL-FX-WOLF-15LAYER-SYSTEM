"""
Centralized Timezone Utilities for TUYUL FX WOLF 15-LAYER SYSTEM

All internal timestamps MUST be stored in UTC (timezone-aware).
All display timestamps MUST show GMT+8 (Asia/Singapore) for user.
External data from providers (Finnhub, brokers) arrives in UTC.

Usage:
    from utils.timezone_utils import now_utc, now_local, utc_to_local
    
    # Get current time
    current_utc = now_utc()  # timezone-aware UTC
    current_local = now_local()  # timezone-aware GMT+8
    
    # Convert between timezones
    local_time = utc_to_local(utc_time)
    utc_time = local_to_utc(local_time)
    
    # Format for display
    formatted = format_local(utc_time)  # Shows in GMT+8
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# System timezone constants
SYSTEM_TZ = ZoneInfo("Asia/Singapore")  # GMT+8 - User's local timezone
DATA_TZ = timezone.utc  # External data always arrives in UTC


def now_utc() -> datetime:
    """
    Get current time as timezone-aware UTC datetime.
    
    Returns:
        datetime: Current time in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    """
    Get current time as timezone-aware GMT+8 (Asia/Singapore) datetime.
    
    Returns:
        datetime: Current time in GMT+8 with timezone info
    """
    return datetime.now(SYSTEM_TZ)


def utc_to_local(dt: datetime) -> datetime:
    """
    Convert UTC datetime to GMT+8 (Asia/Singapore).
    
    Args:
        dt: Datetime to convert (timezone-aware or naive)
        
    Returns:
        datetime: Datetime in GMT+8 with timezone info
    """
    # Ensure the datetime is timezone-aware (assume UTC if naive)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(SYSTEM_TZ)


def local_to_utc(dt: datetime) -> datetime:
    """
    Convert GMT+8 (Asia/Singapore) datetime to UTC.
    
    Args:
        dt: Datetime to convert (timezone-aware or naive)
        
    Returns:
        datetime: Datetime in UTC with timezone info
    """
    # If naive, assume it's in local timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SYSTEM_TZ)
    
    return dt.astimezone(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware and in UTC.
    If naive, assume it's already UTC.
    
    Args:
        dt: Datetime to ensure is UTC
        
    Returns:
        datetime: Datetime in UTC with timezone info
    """
    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=timezone.utc)
    else:
        # Already has timezone - convert to UTC
        return dt.astimezone(timezone.utc)


def format_local(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S GMT+8") -> str:
    """
    Format datetime as GMT+8 string for display.
    
    Args:
        dt: Datetime to format (will be converted to GMT+8)
        fmt: Format string (default shows GMT+8)
        
    Returns:
        str: Formatted datetime string in GMT+8
    """
    local_dt = utc_to_local(dt) if dt.tzinfo == timezone.utc else dt
    return local_dt.strftime(fmt)


def format_utc(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    """
    Format datetime as UTC string for display.
    
    Args:
        dt: Datetime to format (will be converted to UTC)
        fmt: Format string (default shows UTC)
        
    Returns:
        str: Formatted datetime string in UTC
    """
    utc_dt = ensure_utc(dt)
    return utc_dt.strftime(fmt)


def is_trading_session(dt=None) -> str:
    """
    Detect trading session based on GMT+8 hour.

    Session times (GMT+8):
    - ASIA: 07:00-15:00 GMT+8 (23:00-07:00 UTC prev day)
    - LONDON: 15:00-21:00 GMT+8 (07:00-13:00 UTC)
    - NEW_YORK: 21:00-05:00 GMT+8 (13:00-21:00 UTC)

    Args:
        dt: Datetime or ISO string to check (defaults to current time)

    Returns:
        str: Session name ("ASIA", "LONDON", "NEW_YORK", or "OFF_SESSION")
    """
    if dt is None:
        dt = now_local()
    else:
        # Parse ISO string timestamps
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        # Convert to local time for session detection
        dt = utc_to_local(dt)
    
    hour = dt.hour
    
    # Session detection based on GMT+8 local hour
    if 7 <= hour < 15:
        return "ASIA"
    elif 15 <= hour < 21:
        return "LONDON"
    elif hour >= 21 or hour < 5:
        # NEW_YORK session wraps around midnight: 21:00 GMT+8 to 05:00 GMT+8 next day
        return "NEW_YORK"
    else:
        return "OFF_SESSION"


def get_daily_reset_time() -> datetime:
    """
    Get the daily reset time for prop firm drawdown tracking.
    
    Prop firm daily reset happens at midnight GMT+8 (user's local time),
    which is 16:00 UTC on the previous day.
    
    Returns:
        datetime: Today's reset time in UTC (16:00 UTC of previous day)
    """
    # Get current time in local timezone
    local_now = now_local()
    
    # Get midnight today in local timezone
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Convert to UTC (this will be 16:00 UTC of previous day)
    utc_reset_time = local_to_utc(local_midnight)
    
    return utc_reset_time


def format_dual_timezone(dt: datetime) -> str:
    """
    Format datetime showing both UTC and GMT+8 for alerts.
    
    Args:
        dt: Datetime to format
        
    Returns:
        str: Multi-line formatted string with both timezones
    """
    utc_str = format_utc(dt)
    local_str = format_local(dt)
    
    return f"Time (UTC)   : {utc_str}\nTime (Local) : {local_str}"
