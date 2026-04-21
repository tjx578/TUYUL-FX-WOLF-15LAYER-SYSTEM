from __future__ import annotations

import time as pytime

from ingest import dependencies, service_metrics


def test_build_runtime_snapshot_reports_rest_degraded_mode(monkeypatch) -> None:
    monkeypatch.setattr(service_metrics, "ingest_ready", False)
    monkeypatch.setattr(service_metrics, "ingest_degraded", True)
    monkeypatch.setattr(service_metrics, "startup_mode", "stale_cache")
    monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
    monkeypatch.setattr(service_metrics, "producer_present", False)
    monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", 0.0)
    monkeypatch.setattr(service_metrics, "pair_last_tick_ts", {"EURUSD": 0.0})

    snapshot = service_metrics.build_runtime_snapshot(ws_connected=False)

    assert snapshot["ingest_state"] == "DEGRADED_REST_FALLBACK"
    assert snapshot["market_data_mode"] == "REST_DEGRADED"
    assert snapshot["rest_fallback_active"] is True
    assert snapshot["symbols_total"] == 30


def test_build_runtime_snapshot_reports_ready_ws_primary(monkeypatch) -> None:
    monkeypatch.setattr(service_metrics, "ingest_ready", True)
    monkeypatch.setattr(service_metrics, "ingest_degraded", False)
    monkeypatch.setattr(service_metrics, "startup_mode", "warmup")
    monkeypatch.setattr(service_metrics, "enabled_symbol_count", 30)
    monkeypatch.setattr(service_metrics, "producer_present", True)
    monkeypatch.setattr(service_metrics, "producer_last_heartbeat_ts", service_metrics.time())
    monkeypatch.setattr(service_metrics, "pair_last_tick_ts", {"EURUSD": service_metrics.time()})

    snapshot = service_metrics.build_runtime_snapshot(ws_connected=True)

    assert snapshot["ingest_state"] == "READY"
    assert snapshot["market_data_mode"] == "WS_PRIMARY"
    assert snapshot["rest_fallback_active"] is False


def test_mark_pair_tick_uses_local_receipt_time_for_freshness(monkeypatch) -> None:
    fake_now = 1234.5
    monkeypatch.setattr(service_metrics, "time", lambda: fake_now)
    monkeypatch.setattr(service_metrics, "pair_last_tick_ts", {})

    service_metrics.mark_pair_tick("EURUSD", ts=fake_now - 60)

    assert service_metrics.pair_last_tick_ts["EURUSD"] == fake_now


def test_fresh_pair_count_uses_shared_dependencies_tick_map(monkeypatch) -> None:
    now = pytime.time()
    monkeypatch.setattr(service_metrics, "pair_last_tick_ts", dependencies._pair_last_tick_ts)
    dependencies._pair_last_tick_ts.clear()
    dependencies._pair_last_tick_ts.update(
        {
            "EURUSD": now,
            "GBPUSD": now - service_metrics._PRODUCER_FRESHNESS_SEC - 1,
        }
    )

    assert service_metrics.fresh_pair_count() == 1
