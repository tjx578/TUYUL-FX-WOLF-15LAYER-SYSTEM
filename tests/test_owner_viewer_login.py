from __future__ import annotations

import asyncio
import base64
import hashlib
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long!"
USERNAME = "owner@example.test"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def isolated_auth(monkeypatch):
    import api.auth_router as router
    import api.middleware.auth as auth

    monkeypatch.setattr(router, "_owner_login_gate", router._OwnerLoginGate())
    monkeypatch.setattr(auth, "JWT_SECRET", TEST_SECRET)
    monkeypatch.setattr(auth, "JWT_VERIFY_SECRETS", (TEST_SECRET,))


def _password_hash(password: str) -> str:
    salt = b"0123456789abcdef"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    return f"pbkdf2_sha256$210000${encode(salt)}${encode(digest)}"


def _client() -> TestClient:
    from api.auth_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_owner_login_issues_only_scoped_viewer_jwt(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_OWNER_USERNAME", USERNAME)
    monkeypatch.setenv("DASHBOARD_OWNER_PASSWORD_HASH", _password_hash(PASSWORD))
    response = _client().post(
        "/api/auth/owner-login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    session = _client().get("/api/auth/session", headers={"authorization": f"Bearer {token}"})
    assert session.status_code == 200
    body = session.json()
    assert body["role"] == "viewer"
    assert body["scopes"] == ["read:dashboard"]
    assert body["auth_method"] == "jwt"
    assert "set-cookie" not in response.headers


def test_owner_login_rejects_wrong_password_with_generic_error(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_OWNER_USERNAME", USERNAME)
    monkeypatch.setenv("DASHBOARD_OWNER_PASSWORD_HASH", _password_hash(PASSWORD))
    response = _client().post(
        "/api/auth/owner-login",
        json={"username": USERNAME, "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_owner_login_fails_closed_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("DASHBOARD_OWNER_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_OWNER_PASSWORD_HASH", raising=False)
    response = _client().post(
        "/api/auth/owner-login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    assert response.status_code == 401


def test_password_hash_parser_rejects_weak_or_malformed_values() -> None:
    from api.auth_router import _verify_owner_password

    assert not _verify_owner_password(PASSWORD, "")
    assert not _verify_owner_password(PASSWORD, "pbkdf2_sha256$1$c2FsdA$ZGlnZXN0")
    assert not _verify_owner_password(PASSWORD, "scrypt$600000$c2FsdA$ZGlnZXN0")


def test_wrong_username_is_generic(monkeypatch):
    monkeypatch.setenv("DASHBOARD_OWNER_USERNAME", USERNAME)
    monkeypatch.setenv("DASHBOARD_OWNER_PASSWORD_HASH", _password_hash(PASSWORD))
    response = _client().post("/api/auth/owner-login", json={"username": "someone-else", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert response.headers["cache-control"] == "no-store"


def test_owner_token_expiry_is_bounded_independently(monkeypatch):
    import api.auth_router as router
    import api.middleware.auth as auth

    monkeypatch.setattr(router, "_owner_credentials_valid", lambda *_: True)
    monkeypatch.setattr(auth, "TOKEN_EXPIRE_MIN", 60 * 24)
    response = _client().post("/api/auth/owner-login", json={"username": USERNAME, "password": PASSWORD})
    payload = auth.decode_token(response.json()["token"])
    assert payload["exp"] - payload["iat"] == 900
    assert payload["role"] == "viewer"
    assert payload["scopes"] == ["read:dashboard"]
    assert response.headers["cache-control"] == "no-store"
    monkeypatch.setattr(auth.time, "time", lambda: payload["exp"] + 1)
    assert auth.decode_token(response.json()["token"]) is None


def test_direct_core_login_budget_cannot_be_evaded_with_identity_headers(monkeypatch):
    import api.auth_router as router

    calls = []
    monkeypatch.setattr(router, "_owner_credentials_valid", lambda *args: calls.append(args) or False)
    client = _client()
    for i in range(5):
        result = client.post("/api/auth/owner-login", json={"username": str(i), "password": "wrong"})
        assert result.status_code == 401
    rejected = client.post(
        "/api/auth/owner-login",
        json={"username": "new", "password": "wrong"},
        headers={"x-forwarded-for": "203.0.113.99", "x-real-ip": "203.0.113.98"},
    )
    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "60"
    assert len(calls) == 5


def test_login_budget_expires_without_resetting_on_failed_credentials(monkeypatch):
    import api.auth_router as router

    now = [100.0]
    monkeypatch.setattr(router.time, "monotonic", lambda: now[0])
    gate = router._OwnerLoginGate()
    for _ in range(5):
        assert gate.acquire()
        gate.release()
    assert not gate.acquire()
    now[0] += 60
    assert gate.acquire()
    gate.release()


def test_hashing_off_event_loop_and_no_concurrent_hash_queue(monkeypatch):
    from fastapi import HTTPException, Response

    import api.auth_router as router

    started, release = threading.Event(), threading.Event()
    worker_threads = []

    def slow_verify(*_):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(3)
        return False

    monkeypatch.setattr(router, "_owner_credentials_valid", slow_verify)

    async def scenario():
        body = router.OwnerLoginRequest(username=USERNAME, password=PASSWORD)
        first = asyncio.create_task(router.owner_login(body, Response()))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set(), "hash worker never started"
            assert len(worker_threads) == 1
            assert worker_threads[0] != threading.get_ident()
            # This coroutine progressed while the worker was blocked.
            with pytest.raises(HTTPException) as rejected:
                await router.owner_login(body, Response())
            assert rejected.value.status_code == 429
            assert len(worker_threads) == 1
        finally:
            release.set()
            with pytest.raises(HTTPException) as invalid:
                await first
            assert invalid.value.status_code == 401
        assert router._owner_login_gate.acquire()
        router._owner_login_gate.release()

    asyncio.run(scenario())


def test_cancelled_caller_does_not_release_running_hash_slot(monkeypatch):
    from fastapi import Response

    import api.auth_router as router

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_verify(*_):
        started.set()
        try:
            assert release.wait(3)
            return False
        finally:
            finished.set()

    monkeypatch.setattr(router, "_owner_credentials_valid", slow_verify)

    async def scenario():
        task = asyncio.create_task(
            router.owner_login(router.OwnerLoginRequest(username=USERNAME, password=PASSWORD), Response())
        )
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            assert started.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not router._owner_login_gate.acquire()
        finally:
            release.set()
            for _ in range(100):
                if finished.is_set():
                    break
                await asyncio.sleep(0.005)
            assert finished.is_set()

    asyncio.run(scenario())
    assert router._owner_login_gate.acquire()
    router._owner_login_gate.release()


def test_worker_exception_releases_slot(monkeypatch):
    from fastapi import Response

    import api.auth_router as router

    def fail(*_):
        raise RuntimeError("synthetic verification failure")

    monkeypatch.setattr(router, "_owner_credentials_valid", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        asyncio.run(router.owner_login(router.OwnerLoginRequest(username=USERNAME, password=PASSWORD), Response()))
    assert router._owner_login_gate.acquire()
    router._owner_login_gate.release()


@pytest.mark.parametrize("password", ["short", "x" * 1025, "界" * 1024 + "x"])
def test_hash_generator_rejects_out_of_bounds_input_without_output(monkeypatch, capsys, password):
    from scripts import generate_dashboard_owner_password_hash as generator

    monkeypatch.setattr(generator.getpass, "getpass", lambda _: password)
    with pytest.raises(SystemExit):
        generator.main()
    assert capsys.readouterr().out == ""


def test_hash_generator_emits_verifier_not_password(monkeypatch, capsys):
    from api.auth_router import _verify_owner_password
    from scripts import generate_dashboard_owner_password_hash as generator

    monkeypatch.setattr(generator.getpass, "getpass", lambda _: PASSWORD)
    generator.main()
    encoded = capsys.readouterr().out.strip()
    assert PASSWORD not in encoded
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert _verify_owner_password(PASSWORD, encoded)
