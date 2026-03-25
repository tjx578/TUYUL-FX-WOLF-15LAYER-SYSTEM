"""API-facing account read model over Redis ACCOUNT:* hashes.

Canonical location — moved from dashboard/account_manager.py (PR-003).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, cast

from infrastructure.redis_client import get_client
from schemas.trade_models import Account
from storage.redis_client import redis_client


class AccountManager:
    """Read-first account accessor for dashboard/API layers."""

    _memory_accounts: dict[str, Account] = {}

    def list_accounts(self) -> list[Account]:
        accounts: dict[str, Account] = dict(self._memory_accounts)

        with contextlib.suppress(Exception):
            for key in redis_client.client.scan_iter("ACCOUNT:*"):
                raw_id = key.split(":", 1)[1]
                account_id = str(raw_id)
                payload = cast(dict[str, Any], redis_client.client.hgetall(key))
                if payload:
                    accounts[account_id] = self._from_payload(account_id, payload)

        return sorted(accounts.values(), key=lambda a: a.account_id)

    async def list_accounts_async(self) -> list[Account]:
        accounts: dict[str, Account] = dict(self._memory_accounts)

        with contextlib.suppress(Exception):
            client = await get_client()
            async for key in client.scan_iter(match="ACCOUNT:*"):
                raw_id = str(key).split(":", 1)[1]
                account_id = str(raw_id)
                payload = await client.hgetall(str(key))  # type: ignore[misc]  # redis.asyncio ResponseT
                if payload:
                    accounts[account_id] = self._from_payload(account_id, payload)

        return sorted(accounts.values(), key=lambda a: a.account_id)

    def get_account(self, account_id: str) -> Account | None:
        if account_id in self._memory_accounts:
            return self._memory_accounts[account_id]

        try:
            payload = cast(dict[str, Any], redis_client.client.hgetall(f"ACCOUNT:{account_id}"))
        except Exception:
            payload = {}

        if payload:
            account = self._from_payload(account_id, payload)
            self._memory_accounts[account_id] = account
            return account

        return None

    async def get_account_async(self, account_id: str) -> Account | None:
        if account_id in self._memory_accounts:
            return self._memory_accounts[account_id]

        payload: dict[str, Any] = {}
        try:
            client = await get_client()
            payload = await client.hgetall(f"ACCOUNT:{account_id}")  # type: ignore[misc]  # redis.asyncio ResponseT
        except Exception:
            payload = {}

        if payload:
            account = self._from_payload(account_id, payload)
            self._memory_accounts[account_id] = account
            return account

        return None

    def upsert_account(self, account: Account) -> Account:
        self._memory_accounts[account.account_id] = account
        with contextlib.suppress(Exception):
            redis_client.client.hset(
                f"ACCOUNT:{account.account_id}",
                mapping={
                    "name": account.name,
                    "balance": account.balance,
                    "equity": account.equity,
                    "prop_firm": int(account.prop_firm),
                    "max_daily_dd_percent": account.max_daily_dd_percent,
                    "max_total_dd_percent": account.max_total_dd_percent,
                    "max_concurrent_trades": account.max_concurrent_trades,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        return account

    async def upsert_account_async(self, account: Account) -> Account:
        self._memory_accounts[account.account_id] = account
        with contextlib.suppress(Exception):
            client = await get_client()
            await client.hset(  # type: ignore[misc]  # redis.asyncio ResponseT
                f"ACCOUNT:{account.account_id}",
                mapping={
                    "name": account.name,
                    "balance": account.balance,
                    "equity": account.equity,
                    "prop_firm": int(account.prop_firm),
                    "max_daily_dd_percent": account.max_daily_dd_percent,
                    "max_total_dd_percent": account.max_total_dd_percent,
                    "max_concurrent_trades": account.max_concurrent_trades,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        return account

    def _from_payload(self, account_id: str, payload: dict[str, Any]) -> Account:
        return Account(
            account_id=account_id,
            name=str(payload.get("name", account_id)),
            balance=float(payload.get("balance", 0.0) or 0.0),
            equity=float(payload.get("equity", payload.get("balance", 0.0)) or 0.0),
            prop_firm=bool(int(payload.get("prop_firm", 0) or 0)),
            max_daily_dd_percent=float(payload.get("max_daily_dd_percent", 4.0) or 4.0),
            max_total_dd_percent=float(payload.get("max_total_dd_percent", 8.0) or 8.0),
            max_concurrent_trades=int(payload.get("max_concurrent_trades", 1) or 1),
        )
