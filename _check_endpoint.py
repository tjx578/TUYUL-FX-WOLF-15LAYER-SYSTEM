"""Quick check: verify capital-deployment endpoint is mounted and callable."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ["DASHBOARD_JWT_SECRET"] = "test_secret_that_is_at_least_32_chars_long_ok"
os.environ["DASHBOARD_API_KEY"] = "test-api-key-12345"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from schemas.trade_models import Account  # noqa: E402

# Build a mock account
mock_account = MagicMock(spec=Account)
mock_account.account_id = "ACC-001"
mock_account.name = "Test Account"
mock_account.balance = 10000.0
mock_account.equity = 10500.0
mock_account.max_daily_dd_percent = 4.0
mock_account.max_total_dd_percent = 8.0
mock_account.max_concurrent_trades = 3
mock_account.prop_firm = True
mock_account.model_dump.return_value = {
    "account_id": "ACC-001",
    "name": "Test Account",
    "balance": 10000.0,
    "equity": 10500.0,
}

# Mock Redis
mock_redis = AsyncMock()
mock_redis.hgetall.return_value = {
    "daily_dd_percent": "1.2",
    "total_dd_percent": "3.5",
    "open_risk_percent": "0.5",
    "open_trades": "1",
    "circuit_breaker": "0",
    "news_lock": "0",
    "account_locked": "0",
    "compliance_mode": "1",
    "ea_connected": "1",
    "data_source": "EA",
    "account_name": "Test Account",
    "broker": "FTMO",
    "currency": "USD",
    "starting_balance": "10000",
    "current_balance": "10500",
    "equity_high": "11000",
    "leverage": "100",
}

# Mock AccountManager
mock_acct_mgr = AsyncMock()
mock_acct_mgr.list_accounts_async.return_value = [mock_account]

with patch("api.accounts_router.get_client", return_value=mock_redis), \
     patch("api.accounts_router._accounts", mock_acct_mgr):

    from api.accounts_router import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # 1) Check route exists
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set())) for r in router.routes]
    print("=== Registered routes on /api/v1/accounts ===")
    for path, methods in routes:
        print(f"  {methods} {path}")

    cap_dep = [r for r in routes if "capital-deployment" in r[0]]
    if cap_dep:
        print(f"\n[OK] /capital-deployment route found: {cap_dep[0]}")
    else:
        print("\n[FAIL] /capital-deployment route NOT found!")
        sys.exit(1)

    # 2) Hit the endpoint
    print("\n=== GET /api/v1/accounts/capital-deployment ===")
    resp = client.get(
        "/api/v1/accounts/capital-deployment",
        headers={"Authorization": "Bearer test-api-key-12345"},
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Response keys: {list(data.keys())}")
        print(f"  count: {data.get('count')}")
        print(f"  total_usable_capital: {data.get('total_usable_capital')}")
        print(f"  avg_readiness_score: {data.get('avg_readiness_score')}")
        accts = data.get("accounts", [])
        if accts:
            a = accts[0]
            print(f"  accounts[0] readiness_score: {a.get('readiness_score')}")
            print(f"  accounts[0] usable_capital: {a.get('usable_capital')}")
            print(f"  accounts[0] eligibility_flags: {a.get('eligibility_flags')}")
            print(f"  accounts[0] lock_reasons: {a.get('lock_reasons')}")
        print("\n[OK] Backend connection to /api/v1/accounts/capital-deployment is HEALTHY")
    else:
        print(f"Body: {resp.text[:500]}")
        print(f"\n[FAIL] Endpoint returned {resp.status_code}")
        sys.exit(1)
