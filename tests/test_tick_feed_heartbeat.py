from __future__ import annotations

from analysis.tick_feed_heartbeat import TickFeedHeartbeat


def _armed_heartbeat(**overrides) -> TickFeedHeartbeat:
    config = {
        "enabled": True,
        "max_silence_seconds": 300.0,
        "alert_interval_seconds": 600.0,
        "startup_grace_seconds": 600.0,
    }
    config.update(overrides)
    return TickFeedHeartbeat(**config)


def test_disabled_by_default_emits_nothing():
    heartbeat = TickFeedHeartbeat()
    assert heartbeat.enabled is False
    assert heartbeat.check(freshest_tick_epoch=None, market_open=True, now=1_000_000.0) is None


def test_market_closed_never_alarms_even_when_silent():
    heartbeat = _armed_heartbeat()
    for offset in (0.0, 1_000.0, 100_000.0):
        assert heartbeat.check(freshest_tick_epoch=None, market_open=False, now=1_000_000.0 + offset) is None


def test_fresh_tick_keeps_quiet():
    heartbeat = _armed_heartbeat()
    now = 1_000_000.0
    heartbeat.check(freshest_tick_epoch=now - 5.0, market_open=True, now=now)
    assert heartbeat.check(freshest_tick_epoch=now + 995.0, market_open=True, now=now + 1_000.0) is None


def test_silence_past_grace_raises_alarm_then_rate_limits_and_realerts():
    heartbeat = _armed_heartbeat()
    start = 1_000_000.0
    assert heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start) is None
    # Silent past both the grace window and the silence budget.
    alarm = heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start + 700.0)
    assert alarm is not None
    assert alarm["event"] == "tick_feed_heartbeat_alarm"
    assert alarm["status"] == "TICK_FEED_SILENT_MARKET_OPEN"
    assert alarm["alert_number"] == 1
    assert alarm["silence_seconds"] == 700.0
    # Within the re-alert interval: suppressed.
    assert heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start + 900.0) is None
    # Past the re-alert interval: second alarm.
    second = heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start + 1_400.0)
    assert second is not None
    assert second["alert_number"] == 2


def test_recovery_emits_once_then_stays_quiet():
    heartbeat = _armed_heartbeat()
    start = 1_000_000.0
    heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start)
    assert heartbeat.check(freshest_tick_epoch=start, market_open=True, now=start + 700.0) is not None
    recovered = heartbeat.check(freshest_tick_epoch=start + 795.0, market_open=True, now=start + 800.0)
    assert recovered is not None
    assert recovered["event"] == "tick_feed_heartbeat_recovered"
    assert recovered["status"] == "TICK_FEED_RECOVERED"
    assert recovered["alerts_raised"] == 1
    assert recovered["alarm_downtime_seconds"] == 100.0
    assert heartbeat.check(freshest_tick_epoch=start + 895.0, market_open=True, now=start + 900.0) is None


def test_sunday_reopen_grace_holds_friday_stale_tick():
    heartbeat = _armed_heartbeat()
    friday_tick = 1_000_000.0
    reopen = friday_tick + 172_800.0  # two days later
    # Warm the started_at baseline well before the weekend so only the
    # market-open grace is exercised at the reopen.
    heartbeat.check(freshest_tick_epoch=friday_tick, market_open=True, now=friday_tick)
    heartbeat.check(freshest_tick_epoch=friday_tick, market_open=False, now=friday_tick + 3_600.0)
    # Reopen with a two-day-old tick: inside reopen grace -> silent.
    assert heartbeat.check(freshest_tick_epoch=friday_tick, market_open=True, now=reopen) is None
    assert heartbeat.check(freshest_tick_epoch=friday_tick, market_open=True, now=reopen + 500.0) is None
    # Still no ticks after the grace expires -> real alarm.
    alarm = heartbeat.check(freshest_tick_epoch=friday_tick, market_open=True, now=reopen + 700.0)
    assert alarm is not None
    assert alarm["event"] == "tick_feed_heartbeat_alarm"


def test_from_env_reads_flags(monkeypatch):
    monkeypatch.setenv("TICK_FEED_HEARTBEAT_ENABLED", "true")
    monkeypatch.setenv("TICK_FEED_HEARTBEAT_MAX_SILENCE_SECONDS", "120")
    monkeypatch.setenv("TICK_FEED_HEARTBEAT_ALERT_INTERVAL_SECONDS", "240")
    monkeypatch.setenv("TICK_FEED_HEARTBEAT_STARTUP_GRACE_SECONDS", "60")
    heartbeat = TickFeedHeartbeat.from_env()
    assert heartbeat.enabled is True
    assert heartbeat.max_silence_seconds == 120.0
    assert heartbeat.alert_interval_seconds == 240.0
    assert heartbeat.startup_grace_seconds == 60.0


def test_pipeline_wiring_emits_alarm_log(monkeypatch):
    import pipeline.wolf_constitutional_pipeline as wolf_pipeline
    from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
    from utils import market_hours

    monkeypatch.setenv("TICK_FEED_HEARTBEAT_ENABLED", "true")
    monkeypatch.setattr(market_hours, "is_forex_market_open", lambda now=None: True)

    class _Bus:
        def get_feed_timestamps(self):
            return {"EURUSD": 1_000_000.0}

    pipe = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipe._context_bus = _Bus()
    heartbeat = TickFeedHeartbeat.from_env()
    # Pre-warm the state machine past startup grace so the wiring call alarms.
    heartbeat.check(freshest_tick_epoch=1_000_000.0, market_open=True, now=1_000_000.0)
    pipe._tick_feed_heartbeat = heartbeat

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        wolf_pipeline.logger,
        "error",
        lambda template, *args: messages.append(("error", template.format(*args))),
    )
    monkeypatch.setattr(
        wolf_pipeline.logger,
        "warning",
        lambda template, *args: messages.append(("warning", template.format(*args))),
    )
    monkeypatch.setattr(wolf_pipeline.time, "time", lambda: 1_000_700.0)

    pipe._check_tick_feed_heartbeat("EURUSD")

    assert len(messages) == 1
    level, text = messages[0]
    assert level == "error"
    assert "[TickFeedHeartbeat]" in text
    assert '"event":"tick_feed_heartbeat_alarm"' in text
    assert '"status":"TICK_FEED_SILENT_MARKET_OPEN"' in text
    # Second call inside the 30s self rate-limit window stays silent.
    pipe._check_tick_feed_heartbeat("EURUSD")
    assert len(messages) == 1
