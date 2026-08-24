# Channel B Database-Side Account Binding v1 — Proposal Only

## Decision status

```text
DOCUMENT_STATUS=LOCAL_PROPOSAL
PRODUCTION_APPLY=NOT_AUTHORIZED
DATABASE_OR_ACL_MUTATION=NOT_AUTHORIZED
BROKER_ACCESS=NOT_AUTHORIZED
MT5_EA_CHANGE=NO
```

This document defines a review target. It is not executable authorization and
contains no production credential, HMAC key, migration invocation, or live
account identifier.

## Objective and non-goals

The objective is to expose a non-reversible identifier that lets the Channel B
auditor prove that the account observed directly in MT5 is the same account
bound to one trusted backend executor.

Non-goals:

- exposing `account_id`, login suffixes, or unkeyed login hashes to the auditor;
- computing HMAC inside PostgreSQL or embedding a key in SQL;
- expanding the auditor from its six approved views to application tables;
- changing EA behavior, execution authority, broker state, or readiness policy;
- treating database metadata as direct broker truth.

## Binding contract

The database producer and local auditor must implement the same
`w15-account-binding` v1 canonical contract:

```text
login  = authoritative executor account_id as positive canonical ASCII decimal
server = authoritative broker_server as exact-case printable ASCII
digest = HMAC-SHA-256(key_version, domain-separated length-delimited message)
id     = w15ab:v1:<key_id>:<base64url-without-padding-full-digest>
source = EXECUTOR_INSTANCE_ACCOUNT_ID
```

`key_id` is public metadata. The HMAC key is secret and must be supplied to the
backend and local audit process through separately controlled secret stores. It
must not appear in the database, SQL definitions, migration arguments, logs,
reports, screenshots, source control, or Codex configuration.

## Proposed data flow

```text
trusted executor registration/update
  -> validate canonical account_id and exact broker_server
  -> trusted backend binding component reads active HMAC key from secret manager
  -> compute w15ab:v1 identifier in application memory
  -> store identifier + key_id + contract metadata only
  -> approved security-barrier audit view exposes sanitized metadata

direct read-only MT5 observation
  -> local environment supplies matching audit key + key_id
  -> Native MT5 MCP computes identifier in memory
  -> five calls return the same identifier/path/build
  -> reconciler constant-time compares database and MT5 identifiers
```

PostgreSQL never receives the secret key and the auditor never receives the raw
database account identifier.

## Proposed schema

Prefer a dedicated metadata table so rotation does not rewrite the executor
identity row and old/new key versions can overlap safely:

```text
executor_account_binding_identifiers
  executor_id          uuid       not null, FK executor_instances
  scheme               text       = 'w15-account-binding'
  contract_version     text       = 'v1'
  algorithm            text       = 'HMAC-SHA-256'
  key_id               text       public rotation id
  identifier           text       full w15ab:v1 identifier
  binding_source       text       = 'EXECUTOR_INSTANCE_ACCOUNT_ID'
  generated_at         timestamptz not null
  retired_at           timestamptz null
  producer_version     text       bounded non-secret build identifier
  primary key (executor_id, key_id)
```

Required constraints:

- strict identifier and `key_id` shape checks;
- one active row per executor and `key_id`;
- no HMAC key, raw account ID, login suffix, or free-form diagnostic payload;
- immutable identifier, source, scheme, version, and algorithm after insert;
- retirement is the only permitted lifecycle mutation;
- binding generation must reject non-canonical login or non-ASCII server names.

The next audit view revision should left-join the single active metadata row to
the existing account-binding checks and expose only:

```text
executor_id
broker_server
execution_mode
revoked_at
account_binding_identifier
account_binding_key_id
account_binding_scheme
account_binding_version
account_binding_algorithm
account_binding_source
account_binding_generated_at
existing internal mismatch counters
```

The view must not expose `executor_instances.account_id`, `login_hash`, the HMAC
key, or application credentials.

## Migration and rollout plan

Every phase requires explicit production authorization. The current local work
performs none of these steps.

1. **Preflight:** freeze reviewed SQL/code hashes; verify owner and ACL model;
   confirm canonical backend inputs and exact-case server semantics.
2. **Backup:** take a named on-demand backup; record provider backup ID, start/end
   time, size, and completion; verify restore into a disposable environment.
3. **Expand:** create the metadata table and constraints under a NOLOGIN owner;
   do not grant the auditor application-table access.
4. **Producer:** deploy a disabled-by-default trusted backend component that
   computes identifiers in memory from authoritative executor binding fields.
5. **Backfill:** in a bounded transaction, write only reviewed binding metadata;
   record expected versus actual row counts without logging inputs or identifiers.
6. **Audit surface:** revise the security-barrier audit view and grant the auditor
   `SELECT` on that view only.
7. **Revalidate Channel A:** rerun A-B01 through A-B16, including privilege,
   ownership, read-only transaction, mutation count, and view coverage checks.
8. **Read-only Channel B:** with separate authorization, run B-B16 once over an
   explicit UTC window and require coherent identity across all five MT5 calls.
9. **Convergence:** assess Gate E only if both channels pass independently. Keep
   Algo Trading off and canary unauthorized.

## Rotation plan

1. Add a new metadata row with a new `key_id`; do not overwrite the old digest.
2. Keep the old row active only for a bounded, reviewed overlap period.
3. Switch the audit environment to the new key and run synthetic validation.
4. Perform one separately authorized read-only live comparison.
5. Retire the old row only after the new identifier matches.
6. Destroy the old secret through the secret manager and retain only non-secret
   rotation audit metadata.

The reconciler must never try several broker accounts or silently fall back to
an old key after a mismatch.

## ACL impact

Proposed least privilege:

```text
NOLOGIN object owner        = owns table and view
migration role              = temporary DDL authority only
trusted binding producer    = SELECT required executor binding fields;
                              INSERT new metadata; retire approved old row
wolf15_auditor              = SELECT revised audit view only
application runtime roles   = no access unless explicitly required
PUBLIC                      = no table, sequence, function, or schema privilege
```

No sequence privilege is needed if identifiers use application-generated UUIDs
or the composite key. No database function may accept, retrieve, or compute with
the HMAC secret.

## Rollback plan

Rollback is fail-closed:

1. Disable the binding producer.
2. Restore the previous audit view definition and revoke access to the new view
   revision if its verification failed.
3. Preserve metadata rows for forensic review unless deletion is explicitly
   approved; mark them retired rather than rewriting identifiers.
4. Drop the metadata object only after dependency and backup verification.
5. Rerun Channel A privilege and zero-mutation checks.
6. Set `DATABASE_SIDE_IDENTIFIER=NOT_PROVISIONED` and
   `B-B16_LIVE=INCOMPLETE_ACCOUNT_IDENTIFIER`.

Rollback never authorizes a broader table grant, raw login exposure, alternate
broker inspection, EA mutation, or trading.

## Threat analysis

| Threat | Consequence | Required mitigation |
|---|---|---|
| Raw login enumeration | Account identity disclosure | HMAC with at least 256-bit random key; no unkeyed digest or suffix |
| Key stored in SQL/view/log | Offline forgery and enumeration | Secret-manager/environment injection only; secret scans and redacted errors |
| Database writer forges metadata | False account match | Dedicated producer role, immutable rows, constrained source, append/retire lifecycle |
| Old-key replay | Stale binding accepted | Explicit `key_id`, active-row constraint, bounded overlap, no silent fallback |
| Server case normalization | Cross-server collision | Exact-case ASCII canonicalization and byte-length encoding |
| Cross-call terminal/account drift | Mixed broker snapshot | Require identical identifier, server, path fingerprint, and build on all five calls |
| View exposes account ID | Auditor privilege escalation | Security-barrier projection test and negative catalog privilege tests |
| Partial migration/backfill | Ambiguous authority | Nullable expand phase, bounded counts, fail closed until exactly one trusted row |
| Backup is unusable | Irrecoverable rollout | Provider completion evidence plus disposable restore rehearsal |
| Identifier appears in reports | Correlation/privacy leakage | Report only bounded prefixes and booleans; never raw login/key |

## Acceptance gates for a future authorized rollout

```text
BACKUP_COMPLETED_AND_RESTORE_TESTED       = TRUE
RAW_LOGIN_EXPOSED_TO_AUDITOR              = FALSE
HMAC_KEY_IN_DATABASE_OR_LOG               = FALSE
AUDITOR_BASE_TABLE_PRIVILEGE              = NONE
TRUSTED_IDENTIFIER_SOURCE                 = TRUE
ONE_ACTIVE_IDENTIFIER_PER_EXECUTOR        = TRUE
A-B01_THROUGH_A-B16                       = PASS_SAME_RUN
SAME_ACCOUNT_ACROSS_ALL_FIVE_MT5_CALLS    = TRUE
B-B16_LIVE                                = PASS
ORPHAN_UNATTRIBUTED_AMBIGUOUS_COUNT       = 0
ALGO_TRADING                              = OFF
CANARY_AUTHORIZED                         = FALSE
```

Until every applicable gate is measured in an authorized run, the enforced
verdict remains `EXECUTION_READY=FALSE` and `PRODUCTION_READY=FALSE`.
