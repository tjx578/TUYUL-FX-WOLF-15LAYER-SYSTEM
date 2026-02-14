"""
Test suite for timezone utilities
"""

from datetime import UTC, datetime

from utils.timezone_utils import (
    SYSTEM_TZ,
    ensure_utc,
    format_dual_timezone,
    format_local,
    format_utc,
    get_daily_reset_time,
    is_trading_session,
    local_to_utc,
    now_local,
    now_utc,
    utc_to_local,
)


def test_now_utc():
    """Test now_utc returns timezone-aware UTC datetime"""
    dt = now_utc()
    assert dt.tzinfo == UTC
    assert isinstance(dt, datetime)


def test_now_local():
    """Test now_local returns timezone-aware GMT+8 datetime"""
    dt = now_local()
    assert dt.tzinfo == SYSTEM_TZ
    assert isinstance(dt, datetime)


def test_utc_to_local():
    """Test UTC to GMT+8 conversion"""
    # Create a UTC datetime: 2026-02-10 08:00:00 UTC
    utc_dt = datetime(2026, 2, 10, 8, 0, 0, tzinfo=UTC)

    # Convert to GMT+8
    local_dt = utc_to_local(utc_dt)

    # Should be 2026-02-10 16:00:00 GMT+8
    assert local_dt.hour == 16
    assert local_dt.day == 10
    assert local_dt.tzinfo == SYSTEM_TZ


def test_local_to_utc():
    """Test GMT+8 to UTC conversion"""
    # Create a GMT+8 datetime: 2026-02-10 16:00:00 GMT+8
    local_dt = datetime(2026, 2, 10, 16, 0, 0, tzinfo=SYSTEM_TZ)

    # Convert to UTC
    utc_dt = local_to_utc(local_dt)

    # Should be 2026-02-10 08:00:00 UTC
    assert utc_dt.hour == 8
    assert utc_dt.day == 10
    assert utc_dt.tzinfo == UTC


def test_ensure_utc_naive():
    """Test ensure_utc with naive datetime"""
    naive_dt = datetime(2026, 2, 10, 8, 0, 0)
    utc_dt = ensure_utc(naive_dt)

    assert utc_dt.tzinfo == UTC
    assert utc_dt.hour == 8


def test_ensure_utc_aware():
    """Test ensure_utc with timezone-aware datetime"""
    local_dt = datetime(2026, 2, 10, 16, 0, 0, tzinfo=SYSTEM_TZ)
    utc_dt = ensure_utc(local_dt)

    assert utc_dt.tzinfo == UTC
    assert utc_dt.hour == 8


def test_format_utc():
    """Test UTC formatting"""
    dt = datetime(2026, 2, 10, 8, 30, 45, tzinfo=UTC)
    formatted = format_utc(dt)

    assert "2026-02-10 08:30:45 UTC" in formatted


def test_format_local():
    """Test GMT+8 formatting"""
    dt = datetime(2026, 2, 10, 8, 30, 45, tzinfo=UTC)
    formatted = format_local(dt)

    # Should show GMT+8 time (16:30:45)
    assert "2026-02-10 16:30:45 GMT+8" in formatted


def test_is_trading_session_asia():
    """Test session detection - ASIA session"""
    # 10:00 GMT+8 should be ASIA session (07:00-15:00)
    local_dt = datetime(2026, 2, 10, 10, 0, 0, tzinfo=SYSTEM_TZ)
    session = is_trading_session(local_dt)
    assert session == "ASIA"


def test_is_trading_session_london():
    """Test session detection - LONDON session"""
    # 17:00 GMT+8 should be LONDON session (15:00-21:00)
    local_dt = datetime(2026, 2, 10, 17, 0, 0, tzinfo=SYSTEM_TZ)
    session = is_trading_session(local_dt)
    assert session == "LONDON"


def test_is_trading_session_newyork():
    """Test session detection - NEW_YORK session"""
    # 22:00 GMT+8 should be NEW_YORK session (21:00-05:00)
    local_dt = datetime(2026, 2, 10, 22, 0, 0, tzinfo=SYSTEM_TZ)
    session = is_trading_session(local_dt)
    assert session == "NEW_YORK"

    # 02:00 GMT+8 should also be NEW_YORK session
    local_dt = datetime(2026, 2, 10, 2, 0, 0, tzinfo=SYSTEM_TZ)
    session = is_trading_session(local_dt)
    assert session == "NEW_YORK"


def test_is_trading_session_off():
    """Test session detection - OFF_SESSION"""
    # 05:30 GMT+8 should be OFF_SESSION
    local_dt = datetime(2026, 2, 10, 5, 30, 0, tzinfo=SYSTEM_TZ)
    session = is_trading_session(local_dt)
    assert session == "OFF_SESSION"


def test_get_daily_reset_time():
    """Test prop firm daily reset time calculation"""
    reset_time = get_daily_reset_time()

    # Reset time should be in UTC
    assert reset_time.tzinfo == UTC

    # Should be 16:00 UTC (midnight GMT+8)
    assert reset_time.hour == 16
    assert reset_time.minute == 0


def test_format_dual_timezone():
    """Test dual timezone formatting for alerts"""
    dt = datetime(2026, 2, 10, 8, 30, 0, tzinfo=UTC)
    formatted = format_dual_timezone(dt)

    assert "Time (UTC)" in formatted
    assert "Time (Local)" in formatted
    assert "08:30:00 UTC" in formatted
    assert "16:30:00 GMT+8" in formatted


def test_session_conversion_from_utc():
    """Test that UTC times are correctly converted for session detection"""
    # 02:00 UTC should be 10:00 GMT+8 = ASIA session
    utc_dt = datetime(2026, 2, 10, 2, 0, 0, tzinfo=UTC)
    session = is_trading_session(utc_dt)
    assert session == "ASIA"

    # 12:00 UTC should be 20:00 GMT+8 = LONDON session
    utc_dt = datetime(2026, 2, 10, 12, 0, 0, tzinfo=UTC)
    session = is_trading_session(utc_dt)
    assert session == "LONDON"

    # 18:00 UTC should be 02:00 GMT+8 next day = NEW_YORK session
    utc_dt = datetime(2026, 2, 10, 18, 0, 0, tzinfo=UTC)
    session = is_trading_session(utc_dt)
    assert session == "NEW_YORK"
