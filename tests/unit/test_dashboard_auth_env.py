import importlib


def test_auth_uses_legacy_jwt_secret_env(monkeypatch):
    monkeypatch.delenv("DASHBOARD_JWT_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET", "legacy-secret-at-least-32-chars!!")

    import dashboard.backend.auth as auth_module

    reloaded = importlib.reload(auth_module)

    assert reloaded.JWT_SECRET == "legacy-secret-at-least-32-chars!!"
    assert reloaded.JWT_VERIFY_SECRETS == ("legacy-secret-at-least-32-chars!!",)
