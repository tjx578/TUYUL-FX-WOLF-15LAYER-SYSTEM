"""SEC-SVC-01: Health probe authentication & detail sanitization tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.error
import urllib.request

import pytest

from core.health_probe import HealthProbe

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture()
async def probe_server():
    """Start a HealthProbe on a random port and tear down after the test."""
    probe = HealthProbe(port=0, service_name="sec-test")
    server = await asyncio.start_server(probe._handle, "127.0.0.1", 0)
    probe._server = server
    port = server.sockets[0].getsockname()[1]

    task = asyncio.create_task(server.serve_forever())
    yield probe, port

    server.close()
    await server.wait_closed()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _get(port: int, path: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    """Blocking HTTP GET helper."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req, timeout=3)  # noqa: S310
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── /healthz no longer leaks details ─────────────────────────


class TestHealthzSanitized:
    @pytest.mark.asyncio()
    async def test_healthz_no_error_details(self, probe_server):
        probe, port = probe_server
        probe.set_detail("fatal_error", "ConnectionRefused: redis:6379")
        probe.set_detail("runtime_error", "Traceback (most recent...)")
        probe.set_detail("system_state", "RUNNING")

        _, body = await asyncio.to_thread(_get, port, "/healthz")
        assert "fatal_error" not in body
        assert "runtime_error" not in body
        assert "system_state" not in body

    @pytest.mark.asyncio()
    async def test_healthz_still_returns_status(self, probe_server):
        _, port = probe_server
        status, body = await asyncio.to_thread(_get, port, "/healthz")
        assert status == 200
        assert body["status"] == "alive"
        assert body["service"] == "sec-test"
        assert "uptime_sec" in body

    @pytest.mark.asyncio()
    async def test_healthz_dead_no_details(self, probe_server):
        probe, port = probe_server
        probe.set_alive(False)
        probe.set_detail("dead_reason", "task_crash_limit")
        status, body = await asyncio.to_thread(_get, port, "/healthz")
        assert status == 503
        assert "dead_reason" not in body


# ── /readyz no longer leaks details ──────────────────────────


class TestReadyzSanitized:
    @pytest.mark.asyncio()
    async def test_readyz_no_error_details(self, probe_server):
        probe, port = probe_server
        probe.set_detail("circuit_state", "OPEN")
        probe.set_detail("redis", "connected")

        _, body = await asyncio.to_thread(_get, port, "/readyz")
        assert "circuit_state" not in body
        assert "redis" not in body

    @pytest.mark.asyncio()
    async def test_readyz_minimal_body(self, probe_server):
        _, port = probe_server
        status, body = await asyncio.to_thread(_get, port, "/readyz")
        assert status == 200
        assert set(body.keys()) == {"status", "service"}


# ── /status requires authentication ─────────────────────────


class TestStatusAuth:
    @pytest.mark.asyncio()
    async def test_status_no_token_returns_401(self, probe_server, monkeypatch):
        monkeypatch.delenv("HEALTH_PROBE_TOKEN", raising=False)
        _, port = probe_server
        status, body = await asyncio.to_thread(_get, port, "/status")
        assert status == 401
        assert body["error"] == "unauthorized"

    @pytest.mark.asyncio()
    async def test_status_wrong_token_returns_401(self, probe_server, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "correct-secret-token")
        _, port = probe_server
        status, body = await asyncio.to_thread(_get, port, "/status", headers={"Authorization": "Bearer wrong-token"})
        assert status == 401

    @pytest.mark.asyncio()
    async def test_status_valid_bearer_returns_details(self, probe_server, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "correct-secret-token")
        probe, port = probe_server
        probe.set_detail("fatal_error", "redis down")
        probe.set_detail("system_state", "RUNNING")

        status, body = await asyncio.to_thread(
            _get, port, "/status", headers={"Authorization": "Bearer correct-secret-token"}
        )
        assert status == 200
        assert body["fatal_error"] == "redis down"  # no colon → kept as-is
        assert body["system_state"] == "RUNNING"
        assert body["alive"] is True

    @pytest.mark.asyncio()
    async def test_status_valid_query_token(self, probe_server, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "my-probe-key")
        probe, port = probe_server
        probe.set_detail("runtime_error", "timeout")

        status, body = await asyncio.to_thread(_get, port, "/status?token=my-probe-key")
        assert status == 200
        assert body["runtime_error"] == "timeout"

    @pytest.mark.asyncio()
    async def test_status_empty_token_env_denies(self, probe_server, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "")
        _, port = probe_server
        status, _ = await asyncio.to_thread(_get, port, "/status")
        assert status == 401


# ── Parse/auth helper unit tests ─────────────────────────────


class TestParseRequest:
    def test_parse_simple_path(self):
        raw = b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n"
        path, headers = HealthProbe._parse_request(raw)
        assert path == "/healthz"
        assert headers["host"] == "localhost"

    def test_parse_query_token(self):
        raw = b"GET /status?token=abc123 HTTP/1.1\r\n\r\n"
        path, headers = HealthProbe._parse_request(raw)
        assert path == "/status"
        assert headers["_query_token"] == "abc123"

    def test_parse_bearer_header(self):
        raw = b"GET /status HTTP/1.1\r\nAuthorization: Bearer my-token\r\n\r\n"
        path, headers = HealthProbe._parse_request(raw)
        assert path == "/status"
        assert headers["authorization"] == "Bearer my-token"


class TestIsAuthenticated:
    def test_no_env_token_denies(self, monkeypatch):
        monkeypatch.delenv("HEALTH_PROBE_TOKEN", raising=False)
        probe = HealthProbe()
        assert probe._is_authenticated({}) is False

    def test_bearer_match(self, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "secret")
        probe = HealthProbe()
        assert probe._is_authenticated({"authorization": "Bearer secret"}) is True

    def test_bearer_mismatch(self, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "secret")
        probe = HealthProbe()
        assert probe._is_authenticated({"authorization": "Bearer wrong"}) is False

    def test_query_token_match(self, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "secret")
        probe = HealthProbe()
        assert probe._is_authenticated({"_query_token": "secret"}) is True

    def test_query_token_mismatch(self, monkeypatch):
        monkeypatch.setenv("HEALTH_PROBE_TOKEN", "secret")
        probe = HealthProbe()
        assert probe._is_authenticated({"_query_token": "wrong"}) is False


# ── Safe detail key classification ───────────────────────────


class TestSafeDetailKeys:
    def test_safe_keys_included(self):
        probe = HealthProbe()
        probe.set_detail("startup_stage", "running")
        probe.set_detail("warmup", "complete")
        safe = probe._safe_details()
        assert safe == {"startup_stage": "running", "warmup": "complete"}

    def test_sensitive_keys_excluded(self):
        probe = HealthProbe()
        probe.set_detail("fatal_error", "boom")
        probe.set_detail("runtime_error", "timeout")
        probe.set_detail("system_state", "RUNNING")
        probe.set_detail("circuit_state", "OPEN")
        probe.set_detail("dead_reason", "crash")
        safe = probe._safe_details()
        assert safe == {}


# ── Error detail sanitization (DEBT-SVC-13 hardening) ────────


class TestErrorDetailSanitization:
    def test_colon_in_fatal_error_stripped(self):
        probe = HealthProbe()
        probe.set_detail("fatal_error", "ConnectionRefusedError: redis://user:pass@host:6379")
        assert probe._details["fatal_error"] == "ConnectionRefusedError"

    def test_colon_in_runtime_error_stripped(self):
        probe = HealthProbe()
        probe.set_detail("runtime_error", "Traceback: File /app/main.py line 42")
        assert probe._details["runtime_error"] == "Traceback"

    def test_colon_in_dead_reason_stripped(self):
        probe = HealthProbe()
        probe.set_detail("dead_reason", "ingest_crash_limit: exceeded 3 restarts")
        assert probe._details["dead_reason"] == "ingest_crash_limit"

    def test_no_colon_kept_as_is(self):
        probe = HealthProbe()
        probe.set_detail("fatal_error", "redis down")
        assert probe._details["fatal_error"] == "redis down"

    def test_non_error_key_not_sanitized(self):
        probe = HealthProbe()
        probe.set_detail("system_state", "RUNNING: extra info")
        assert probe._details["system_state"] == "RUNNING: extra info"

    def test_empty_value_returns_error(self):
        probe = HealthProbe()
        probe.set_detail("fatal_error", "")
        assert probe._details["fatal_error"] == "error"
