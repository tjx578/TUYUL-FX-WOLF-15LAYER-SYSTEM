"""Durable Channel-B account-binding identity producer.

Separation of authority, deliberately:

``executor_reconciliation_bindings``  D0 snapshot-bound reconciliation evidence
``executor_account_binding_identifiers``  durable Channel-B account identity

Both derive their identifier from the same primitive in
:mod:`ops.mt5_mcp.account_binding`. They do not share a lifecycle: the D0 row is
keyed by ``executor_id`` alone and is rewritten in place, while an identity row is
keyed by ``(executor_id, key_id)`` and is immutable once written. Retirement is an
explicit mutation, never an overwrite, so a bounded key-rotation overlap can be
expressed and audited.

This producer is a privileged backend path. The account identity is read only from
``executor_instances``; no login, server, key id, or identifier is ever accepted
from a caller, a terminal report, or MT5. The HMAC key is read from the audit-local
environment contract and never reaches PostgreSQL.
"""

from __future__ import annotations

import os
from typing import Any, Final
from uuid import UUID

from ops.mt5_mcp import account_binding

PRODUCER_VERSION: Final = "channel-b-account-binding-identity-v1"

#: Identity must be provable while an executor is still in read-only SHADOW.
#: Requiring DEMO would force a mode change purely to obtain identity, and LIVE is
#: out of scope for this milestone.
SUPPORTED_EXECUTION_MODES: Final = frozenset({"SHADOW", "DEMO"})

AUDIT_VIEW: Final = "wolf15_audit.account_binding_identity_v1"


class AccountBindingIdentityError(ValueError):
    """Fail-closed identity error carrying a stable, non-secret code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _environment_key() -> tuple[bytes, str]:
    """Resolve the audit-local HMAC key and its public key id, fail-closed."""

    try:
        secret_key = account_binding.decode_secret_key(os.getenv(account_binding.KEY_ENV, ""))
        key_id = account_binding.validate_key_id(os.getenv(account_binding.KEY_ID_ENV, ""))
    except account_binding.AccountBindingError as exc:
        raise AccountBindingIdentityError(exc.code) from exc
    return secret_key, key_id


async def _authoritative_executor(connection: Any, executor_id: UUID | str) -> Any:
    executor = await connection.fetchrow(
        "SELECT * FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE", str(executor_id)
    )
    if not executor:
        raise AccountBindingIdentityError("ACCOUNT_BINDING_EXECUTOR_UNKNOWN")
    if executor["revoked_at"] is not None:
        raise AccountBindingIdentityError("ACCOUNT_BINDING_EXECUTOR_REVOKED")
    if executor["execution_mode"] not in SUPPORTED_EXECUTION_MODES:
        raise AccountBindingIdentityError("ACCOUNT_BINDING_EXECUTION_MODE_UNSUPPORTED")
    return executor


async def _audit_row(connection: Any, executor_id: UUID | str, key_id: str) -> dict[str, Any]:
    row = await connection.fetchrow(
        f"SELECT * FROM {AUDIT_VIEW} WHERE executor_id=$1::uuid AND key_id=$2",  # noqa: S608 - constant view name
        str(executor_id),
        key_id,
    )
    if row is None:
        raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_NOT_PROJECTED")
    return dict(row)


async def produce_account_binding_identity(connection: Any, executor_id: UUID | str) -> dict[str, Any]:
    """Derive and persist the durable Channel-B identity for one executor.

    Idempotent for an identical ``(executor_id, key_id, identifier)``. If the same
    ``key_id`` already maps to a different identifier the call fails closed rather
    than rewriting history: that means the underlying account binding changed under
    a key version that was already published, which an auditor must see.

    The caller owns the transaction.
    """

    executor = await _authoritative_executor(connection, executor_id)
    secret_key, key_id = _environment_key()
    try:
        identifier = account_binding.identifier(
            secret_key=secret_key,
            key_id=key_id,
            login=executor["account_id"],
            server=executor["broker_server"],
        )
    except account_binding.AccountBindingError as exc:
        # An opaque or non-canonical account_id cannot be bound. Provisioning has to
        # establish the real binding; no terminal report can repair this.
        raise AccountBindingIdentityError(exc.code) from exc

    existing = await connection.fetchrow(
        """SELECT identifier, broker_server, retired_at
             FROM executor_account_binding_identifiers
            WHERE executor_id=$1::uuid AND key_id=$2 FOR UPDATE""",
        str(executor_id),
        key_id,
    )
    if existing is not None:
        if not account_binding.identifiers_match(existing["identifier"], identifier):
            raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_CONFLICT")
        if existing["broker_server"] != executor["broker_server"]:
            raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_CONFLICT")
        if existing["retired_at"] is not None:
            raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_RETIRED")
        return await _audit_row(connection, executor_id, key_id)

    await connection.execute(
        """INSERT INTO executor_account_binding_identifiers
             (executor_id, key_id, scheme, contract_version, algorithm,
              identifier, binding_source, broker_server, producer_version)
           VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9)""",
        str(executor_id),
        key_id,
        account_binding.SCHEME,
        account_binding.VERSION,
        account_binding.ALGORITHM,
        identifier,
        account_binding.DATABASE_SOURCE,
        executor["broker_server"],
        PRODUCER_VERSION,
    )
    return await _audit_row(connection, executor_id, key_id)


async def retire_account_binding_identity(connection: Any, executor_id: UUID | str, key_id: object) -> dict[str, Any]:
    """Retire one key version without rewriting its identifier.

    Retirement is the only supported mutation. A retired row stays readable in the
    base table for provenance but leaves the audit projection, so it can never
    satisfy a Channel-B identity comparison afterwards.
    """

    try:
        validated_key_id = account_binding.validate_key_id(key_id)
    except account_binding.AccountBindingError as exc:
        raise AccountBindingIdentityError(exc.code) from exc

    row = await connection.fetchrow(
        """UPDATE executor_account_binding_identifiers
              SET retired_at = clock_timestamp()
            WHERE executor_id=$1::uuid AND key_id=$2 AND retired_at IS NULL
        RETURNING executor_id, key_id, identifier, retired_at""",
        str(executor_id),
        validated_key_id,
    )
    if row is None:
        raise AccountBindingIdentityError("ACCOUNT_BINDING_IDENTITY_NOT_ACTIVE")
    return dict(row)


async def active_account_binding_identities(connection: Any, executor_id: UUID | str) -> list[dict[str, Any]]:
    """Return every active projected identity for one executor, key_id ordered.

    More than one row is legitimate during a bounded rotation overlap. Selecting
    which one is eligible is the reconciler's job and is driven by the direct MT5
    key id, never by recency.
    """

    rows = await connection.fetch(
        f"SELECT * FROM {AUDIT_VIEW} WHERE executor_id=$1::uuid ORDER BY key_id",  # noqa: S608 - constant view name
        str(executor_id),
    )
    return [dict(row) for row in rows]
