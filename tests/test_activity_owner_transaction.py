"""Owner helper transaction preconditions; this is not PostgreSQL acceptance."""

import asyncio
from dataclasses import asdict
from uuid import uuid4

import pytest

from storage.strategy_5scr_activity_consumer import LifecycleOwnerFence, bind_owner, lock_symbol, transfer_owner
from tests.test_activity_delivery_contract import scope


class OwnerConnection:
    def __init__(self, active):
        self.active = active
        self.calls = []
        self.fence = LifecycleOwnerFence("EURUSD", scope().scope_hash, scope().lifecycle_owner_id, 1, uuid4())

    def is_in_transaction(self):
        return self.active

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if sql.startswith("INSERT INTO public.strategy_5scr_owner_fences_v1"):
            self.fence = LifecycleOwnerFence(*args)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "bind_5scr_lifecycle_owner_v1" in sql:
            return {"bound": tuple(asdict(self.fence).values()) == args}
        return asdict(self.fence)


@pytest.mark.parametrize("operation", ["lock", "bind", "transfer"])
def test_owner_helpers_reject_autocommit_before_any_sql(operation):
    connection = OwnerConnection(active=False)
    original = connection.fence

    async def run():
        if operation == "lock":
            await lock_symbol(connection, "EURUSD")
        elif operation == "bind":
            await bind_owner(connection, original)
        else:
            await transfer_owner(connection, symbol="EURUSD", scope=scope(), expected_generation=1)

    with pytest.raises(ValueError, match="^LIFECYCLE_OWNER_TRANSACTION_REQUIRED$"):
        asyncio.run(run())
    assert connection.calls == [] and connection.fence == original


def test_transactional_handover_rotates_owner_and_rejects_old_binding():
    connection = OwnerConnection(active=True)
    old = connection.fence

    async def run():
        new = await transfer_owner(connection, symbol="EURUSD", scope=scope(), expected_generation=1)
        assert new.generation == 2 and new.token != old.token
        assert connection.fence == new
        with pytest.raises(ValueError, match="STALE_OR_UNBOUND_LIFECYCLE_OWNER"):
            await bind_owner(connection, old)
        await bind_owner(connection, new)
        assert connection.calls[-1][1] == tuple(asdict(new).values())

    asyncio.run(run())
