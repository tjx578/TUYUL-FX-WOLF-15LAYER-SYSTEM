# D0 authenticated reconciliation

Base: PR #419, `cb14d25ae35585d08e743aebfb141c35dd81f2d6`.
Scope: independent evidence for the existing engineering DEMO canary only.
No strategy authority, SHADOW rerun, deployment, account promotion, or broker action.

## Contract and trust

1. The backend producer reads `executor_instances` and the persisted snapshot in
   a transaction. It derives the existing versioned HMAC identifier using
   `account_id` as the canonical MT5 decimal login and the exact-case broker
   server. Opaque/nondecimal IDs fail closed; they require independently approved
   provisioning, never a value copied from a terminal report. Re-registration
   cannot overwrite the existing account/server/login-hash binding.
2. `wolf15_audit.backend_account_identity_v1` projects only the derived identifier,
   executor, server, binding version and snapshot ID/digest. The raw account,
   login hash and snapshot payload remain outside this view. Stale binding rows
   disappear when the authoritative executor or stored snapshot differs.
3. The controlled Channel B collector uses the existing five read tools and
   dedicated auditor transaction. It recomputes reconciliation from its own
   reads, requires MATCHED, DEMO (`trade_mode=0`), flat current positions/orders,
   complete bounded measurements, and the backend identity projection. It signs
   a purpose/version-separated attestation, not an imported legacy report.
4. Authentication is HMAC-SHA256 under a **separate issuer key**, not the account
   HMAC key or command key. The key ID is matched against trusted configuration,
   not trusted because it appears in a report. A plain report hash is not MAC
   authentication. This authenticates the configured collector/backend trust
   domain; both holders of this symmetric key can issue MACs. It does not provide
   nonrepudiation or remote attestation of a Windows process. Arbitrary processes,
   executor clients and auditors must not receive this key.
5. Backend import verifies issuer, exact binding/version/snapshot and freshness,
   then persists the proof. New valid evidence revokes prior evidence for that
   executor atomically. Duplicate IDs cannot overwrite or reactivate a receipt.
6. Builder verifies evidence and pins its ID and full payload digest in the signed
   command. Enqueue and arm independently read and lock the bound database rows,
   authenticate again with current key configuration, and verify the pinned
   digest, ACTIVE status, identity and snapshot. Expiry is capped at 30 seconds
   from the oldest collection start, not from upload. A changed/revoked receipt
   or binding cannot arm a previously queued command. Locks serialize evidence
   replacement with gate transitions; these checks do not promise evidence
   remains valid indefinitely after a completed arm transaction.

`AccountSnapshotV1.broker_ledger_reconciled` remains executor observation. Its
value cannot grant authority. The signed canary guard's `true` value reflects
backend verification. All other DEMO, dedicated-EA, flat-account, minimum-volume,
SL/TP, one-shot, idempotency, heartbeat and kill-switch checks remain in place.

## Local/disposable and actual operations

The integration fixture exercises migrated PostgreSQL and the existing real
repository/authority path, with synthetic broker reads and disposable test keys.
It does not claim live broker/database reconciliation. It tests each of builder,
enqueue and arm against missing, forged, stale, wrong-account, wrong-server and
revoked proofs, plus replacement, binding/snapshot drift and heartbeat-only bypass.

Migration: `20260910_02` follows the existing merged head `20260910_01`. It creates
only identity/evidence tables and the narrow audit view. If `wolf15_auditor`
already exists, it grants usage/select on this projection only and revokes direct
access to the new tables. Creating or changing production roles is not automatic.
The backend producer/importer needs the reviewed existing backend writer role;
consumer access needs SELECT on the new tables. The auditor never gets writes.

Commands are `python -m scripts.manage_d0_reconciliation`:

- `identity --executor-id UUID --out identity.json`: backend writer context,
  reads the governed binding and publishes the derived identity for its latest
  stored snapshot. Repeating it on the same binding/snapshot preserves version.
- `collect --config PATH --out attestation.json`: dedicated auditor and local
  read-only MT5 MCP context; derives and authenticates a fresh reconciliation.
- `import --evidence attestation.json --out receipt.json`: backend writer context,
  validates the MAC and records the evidence. It cannot enqueue or arm.

Identity producer and MT5 collector use existing `WOLF15_ACCOUNT_BINDING_KEY_B64URL`
and `WOLF15_ACCOUNT_BINDING_KEY_ID` from the secure process environment. Collector
and verifier separately use `WOLF15_RECONCILIATION_ISSUER_KEY_B64URL` (at least
32 random bytes, unpadded base64url) and `WOLF15_RECONCILIATION_ISSUER_KEY_ID`.
There is no production key, fallback secret, automatic rotation or credentials
in source. Never pass keys as CLI arguments or expose them to the MT5 child.
A new issuer key ID invalidates previously signed proofs. Identity rotation
requires refreshing the backend projection with the matching identity key ID.

Actual collection requires these roles/keys and this migration/source deployed
through the existing operational mechanism. No production migration or order
has been executed by this source change. CI health cannot establish broker readiness.
