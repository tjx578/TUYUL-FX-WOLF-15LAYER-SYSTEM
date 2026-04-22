from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from execution.execution_router import router


def test_queue_endpoint_exposes_execution_runtime_status() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with (
        patch("execution.execution_router._ea_manager.queue_snapshot", return_value={
            "queue_depth": 1,
            "queue_max": 200,
            "running": True,
            "overload_mode": "reject_new",
            "overload_rejections": 0,
            "overload_drops": 0,
        }),
        patch("execution.execution_router._broker.runtime_snapshot", return_value={
            "execution_enabled": False,
            "broker_calls_suppressed": True,
            "ea_url": "http://ea-bridge:8081",
        }),
    ):
        response = client.get("/api/v1/execution/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queue_depth": 1,
        "max_size": 200,
        "running": True,
        "overload_mode": "reject_new",
        "overload_rejections": 0,
        "overload_drops": 0,
        "execution_enabled": False,
        "broker_calls_suppressed": True,
        "ea_url": "http://ea-bridge:8081",
    }
