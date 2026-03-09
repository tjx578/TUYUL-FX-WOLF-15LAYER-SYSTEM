from __future__ import annotations

from pathlib import Path
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from services.worker import montecarlo_job, nightly_backtest, regime_recalibration


class _FakeMCResult:
    passed_threshold = True

    def to_dict(self) -> dict[str, object]:
        return {"portfolio_win_probability": 0.61, "passed_threshold": True}


class _FakeMCEngine:
    def run(self, return_matrix: dict[str, list[float]]) -> _FakeMCResult:
        assert len(return_matrix) >= 2
        return _FakeMCResult()


class _FakeWFResult:
    passed = True
    window_count = 3

    def to_dict(self) -> dict[str, object]:
        return {"avg_win_rate": 0.58, "passed": True}


class _FakeWFValidator:
    def run(self, returns: list[float]) -> _FakeWFResult:
        assert len(returns) >= 130
        return _FakeWFResult()


class _FakeTuner:
    def __init__(self, window_size: int, update_interval: int) -> None:
        super().__init__()
        self.window_size = window_size
        self.update_interval = update_interval
        self.seen: list[float] = []

    def add_vr(self, vr: float) -> None:
        self.seen.append(vr)

    def tune_and_update(self) -> None:
        pass


class _FakePath:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__()
        pass

    def exists(self) -> bool:
        return False

    def read_text(self, encoding: str = "utf-8") -> str:
        return "{}"


def test_montecarlo_job_runs_and_publishes(monkeypatch: MonkeyPatch) -> None:
    published: dict[str, object] = {}

    def _payload_loader(**_kwargs: Any) -> dict[str, list[float]]:
        return {
            "EURUSD": [10.0, -5.0, 12.0, -7.0],
            "GBPUSD": [8.0, -6.0, 11.0, -4.0],
        }

    def _capture_publish(_key: str, payload: dict[str, object]) -> None:
        published.update(payload)

    def _artifact_writer(_path: str, _payload: dict[str, object]) -> Path:
        return Path("dummy.json")

    monkeypatch.setattr(montecarlo_job, "load_json_payload", _payload_loader)
    monkeypatch.setattr(montecarlo_job, "_build_engine", lambda: _FakeMCEngine())
    monkeypatch.setattr(montecarlo_job, "publish_result", _capture_publish)
    monkeypatch.setattr(montecarlo_job, "write_json_artifact", _artifact_writer)

    montecarlo_job.run()

    assert published["job"] == "montecarlo"
    assert "result" in published


def test_montecarlo_job_skips_on_insufficient_pairs(monkeypatch: MonkeyPatch) -> None:
    called = {"publish": False}

    def _payload_loader(**_kwargs: Any) -> dict[str, list[float]]:
        return {"EURUSD": [1.0, -1.0]}

    def _capture_publish(*_args: object, **_kwargs: object) -> None:
        called["publish"] = True

    monkeypatch.setattr(montecarlo_job, "load_json_payload", _payload_loader)
    monkeypatch.setattr(montecarlo_job, "publish_result", _capture_publish)

    montecarlo_job.run()

    assert called["publish"] is False


def test_nightly_backtest_runs_and_publishes(monkeypatch: MonkeyPatch) -> None:
    published: dict[str, object] = {}

    def _payload_loader(**_kwargs: Any) -> list[float]:
        return [1.0] * 150

    def _capture_publish(_key: str, payload: dict[str, object]) -> None:
        published.update(payload)

    def _artifact_writer(_path: str, _payload: dict[str, object]) -> Path:
        return Path("dummy.json")

    monkeypatch.setattr(nightly_backtest, "load_json_payload", _payload_loader)
    monkeypatch.setattr(nightly_backtest, "WalkForwardValidator", lambda: _FakeWFValidator())
    monkeypatch.setattr(nightly_backtest, "publish_result", _capture_publish)
    monkeypatch.setattr(nightly_backtest, "write_json_artifact", _artifact_writer)

    nightly_backtest.run()

    assert published["job"] == "nightly_backtest"
    assert published["returns_count"] == 150


def test_regime_recalibration_runs_and_publishes(monkeypatch: MonkeyPatch) -> None:
    published: dict[str, object] = {}

    def _payload_loader(**_kwargs: Any) -> list[float]:
        return [1.0] * 40

    def _capture_publish(_key: str, payload: dict[str, object]) -> None:
        published.update(payload)

    def _artifact_writer(_path: str, _payload: dict[str, object]) -> Path:
        return Path("dummy.json")

    monkeypatch.setattr(regime_recalibration, "load_json_payload", _payload_loader)
    monkeypatch.setattr(regime_recalibration, "RegimeAutoTuner", _FakeTuner)
    monkeypatch.setattr(regime_recalibration, "Path", _FakePath)
    monkeypatch.setattr(regime_recalibration, "publish_result", _capture_publish)
    monkeypatch.setattr(regime_recalibration, "write_json_artifact", _artifact_writer)

    regime_recalibration.run()

    assert published["job"] == "regime_recalibration"
    assert published["vr_count"] == 40
