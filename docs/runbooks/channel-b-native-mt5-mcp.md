# Channel B — Native MT5 Read-Only MCP

## Current verdict

Local contract status on branch `codex/channel-b-account-binding-v1`:

```text
CHANNEL_B_LOCAL_IMPLEMENTATION=PASS_REPORTED
ACCOUNT_BINDING_CONTRACT=w15ab:v1
DIRECT_IDENTIFIER=HMAC_SHA256_KEY_VERSIONED
DATABASE_SIDE_IDENTIFIER=CONTRACT_ENFORCED_NOT_PROVISIONED
B-B16_SYNTHETIC=EXECUTED_PASS
B-B16_LIVE=INCOMPLETE_ACCOUNT_IDENTIFIER
EXECUTION_READY=FALSE
PRODUCTION_READY=FALSE
```

The local v2 implementation and its synthetic tests do not replace or upgrade
the last production observation below. No database view, ACL, EA, terminal,
broker, deployment, or production row was changed while implementing v2.

Verified on `2026-08-23T20:59Z` against the already-running terminal at
`C:\Program Files\XM Global MT5\terminal64.exe`:

```text
CHANNEL_B_MCP_REGISTRATION=READY
MCP_TRANSPORT=configured_stdio
MCP_TOOL_SURFACE=EXACT_5_READ_TOOLS
MCP_WRITE_TOOL_COUNT=0
DIRECT_BROKER_STATE=MEASURED
BROKER_RECONCILIATION=INCOMPLETE_ACCOUNT_IDENTIFIER
B-B16=EXECUTED_INCOMPLETE
EXECUTION_READY=FALSE
PRODUCTION_READY=FALSE
```

`DIRECT_BROKER_STATE=MEASURED` is scoped to the live calls and their returned
timestamps/windows. It does not mean that the broker is permanently empty and
does not establish reconciliation with database mirrors, execution commands,
or EA state.

## Objective and authority boundary

Channel B supplies direct, read-only evidence from the currently active MT5
terminal. It exists to close the evidence gap that database mirrors cannot
close by themselves.

Allowed authority:

1. Read bounded account status.
2. Read current open positions.
3. Read current pending orders.
4. Read deal history over an explicit UTC window.
5. Read order history over an explicit UTC window.

Explicit non-goals:

- no account login or account switching;
- no order placement, checking, cancellation, or modification;
- no position closing or SL/TP modification;
- no symbol selection, chart control, screenshot, EA control, or terminal settings;
- no persistence, background synchronization, or database writes;
- no inference of broker reconciliation or production readiness from an empty snapshot.

## Architecture

```text
Codex desktop / CLI
  -> official Codex MCP configuration (~/.codex/config.toml)
  -> local stdio child process
  -> isolated Python environment
  -> WOLF15 Native MT5 Read-Only MCP
  -> MetaQuotes MetaTrader5 Python package
  -> exact already-running XM Global MT5 terminal
  -> broker account selected in that terminal
```

There is no network listener and no MCP API key. The server refuses to call
`MetaTrader5.initialize()` unless an operating-system process is running from
the exact configured executable path. This prevents the read tool from silently
launching or binding to a different installed MT5 terminal.

MetaQuotes documents the native Python read functions used here:

- <https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5ordersget_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py>

Codex documents `~/.codex/config.toml`, stdio servers, `enabled_tools`, and
per-server approval policy at <https://developers.openai.com/codex/mcp>.

## Registered Codex contract

The active global entry is `mcp_servers.native_mt5_readonly`. Its effective
non-secret configuration is:

```toml
[mcp_servers.native_mt5_readonly]
command = 'C:\Users\INTEL\.codex\mcp-envs\native-mt5-readonly\Scripts\python.exe'
args = ['C:\Users\INTEL\OneDrive\Documents\GitHub\TUYUL-FX-WOLF-15LAYER-SYSTEM\ops\mt5_mcp\server.py']
enabled = true
required = false
enabled_tools = [
  "mt5_account_get",
  "mt5_positions_get",
  "mt5_orders_get",
  "mt5_history_deals_get",
  "mt5_history_orders_get",
]
default_tools_approval_mode = "prompt"
startup_timeout_sec = 20
tool_timeout_sec = 30

[mcp_servers.native_mt5_readonly.env]
MT5_CONNECT_TIMEOUT_MS = "10000"
MT5_MAX_HISTORY_DAYS = "31"
MT5_MAX_ROWS = "1000"
MT5_TERMINAL_PATH = 'C:\Program Files\XM Global MT5\terminal64.exe'
```

No login, password, HMAC key, server credential, bearer token, database URL, or
account number may be stored in Codex configuration. The MCP binds to the
account already selected and authenticated inside the pinned terminal. For v2,
the launcher passes the HMAC key and public `key_id` from its local process
environment to the short-lived MCP child. Missing or invalid key material makes
all account-bound reads fail closed as `NOT_MEASURED`.

## Tool contract

| Tool | Native read | Output authority | Limit |
|---|---|---|---|
| `mt5_account_get` | `account_info()` | current account snapshot | one account; raw login and login suffix are never returned |
| `mt5_positions_get` | `positions_get()` | current broker positions | maximum 1,000 records |
| `mt5_orders_get` | `orders_get()` | current pending broker orders | maximum 1,000 records |
| `mt5_history_deals_get` | `history_deals_get()` | broker deal history | default 7 days; maximum 31 days and 1,000 returned rows |
| `mt5_history_orders_get` | `history_orders_get()` | broker order history | default 7 days; maximum 31 days and 1,000 returned rows |

All five tools carry MCP annotations equivalent to read-only, non-destructive,
and idempotent. Codex applies an independent allowlist with the same five names.

Broker-controlled free-text fields such as order/deal comments and external IDs
are excluded. Native error descriptions are not forwarded; only stable error
codes are returned.

## Measurement semantics

Every successful v2 response contains:

- `observed_at_utc`;
- a full `w15ab:v1:<key_id>:<digest>` HMAC account identifier;
- the public binding scheme, version, algorithm, and `key_id`;
- a fingerprint of the pinned terminal path and terminal build;
- `measurement_state`;
- `record_count`, `source_record_count`, and truncation state;
- an explicit UTC window for history calls.

Allowed states:

| State | Meaning |
|---|---|
| `MEASURED` | the native call succeeded and returned at least one record |
| `MEASURED_EMPTY` | the native call succeeded and returned zero records for the exact snapshot/window |
| `NOT_MEASURED` | terminal/configuration/connection evidence was unavailable |
| `ERROR` | the request or native read failed; record counts remain null |

An unavailable or failed call never becomes `0` or `MEASURED_EMPTY`.

## HMAC account-binding contract

Environment-only inputs:

```text
WOLF15_ACCOUNT_BINDING_KEY_B64URL = unpadded base64url, at least 32 random bytes
WOLF15_ACCOUNT_BINDING_KEY_ID     = public rotation identifier
```

Canonical input:

```text
domain = "WOLF15\0ACCOUNT_BINDING\0V1\0"
login  = positive ASCII decimal, no sign, whitespace, or leading zero
server = exact-case printable ASCII, 1..128 bytes
message = domain || u32be(login_byte_length) || login ||
                   u32be(server_byte_length) || server
identifier = "w15ab:v1:" || key_id || ":" ||
             base64url_no_padding(HMAC_SHA256(key, message))
```

The implementation compares full validated identifiers with
`hmac.compare_digest`. It does not lowercase the broker server and does not
return the raw login, its last four digits, the key, or an unkeyed login hash.

Generate a fresh key in an ephemeral PowerShell process without printing it:

```powershell
$BindingKeyBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($BindingKeyBytes)
$env:WOLF15_ACCOUNT_BINDING_KEY_B64URL = `
    [Convert]::ToBase64String($BindingKeyBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$env:WOLF15_ACCOUNT_BINDING_KEY_ID = 'audit-2026-01'
[Array]::Clear($BindingKeyBytes, 0, $BindingKeyBytes.Length)
```

Do not echo either environment value, capture it in a screenshot, persist it in
shell profiles, `.env`, Codex configuration, source control, SQL, reports, or
logs. Distribute the corresponding backend key only through an independently
approved secret-management path.

Rotation procedure:

1. Generate a new key and monotonically distinct `key_id`.
2. Have the trusted backend compute the new database-side identifier from its
   authoritative executor account binding; never compute it in SQL.
3. Keep old and new metadata separately during an approved overlap window.
4. Set the local environment to the new key and verify a synthetic comparison.
5. Run an explicitly authorized read-only B-B16 comparison.
6. Retire the old metadata only after the new live identifier matches. A key-id
   mismatch is a blocker, never an invitation to try multiple broker accounts.

## Channel B verification gates

| Gate | Requirement | Current evidence | Verdict |
|---|---|---|---|
| B-B01 | Registered through the official Codex MCP configuration | `codex mcp get native_mt5_readonly` resolves the global entry | PASS |
| B-B02 | Local stdio transport only | configured subprocess completed an MCP list/call cycle | PASS |
| B-B03 | Isolated and pinned runtime | MetaTrader5 `5.0.6090`, MCP `2.0.0`, psutil `7.2.2` | PASS |
| B-B04 | Exact terminal binding | process and native terminal path both match XM Global MT5 | PASS |
| B-B05 | No stored broker credential | config contains only terminal path and numeric bounds | PASS |
| B-B06 | Exact five-tool allowlist | server registry and Codex `enabled_tools` match | PASS |
| B-B07 | Tool metadata is read-only/non-destructive | MCP registry annotations verified by test | PASS |
| B-B08 | Account can be measured | one sanitized direct account record returned | PASS |
| B-B09 | Current positions can be measured | successful current snapshot, zero records | PASS (`MEASURED_EMPTY`) |
| B-B10 | Current pending orders can be measured | successful current snapshot, zero records | PASS (`MEASURED_EMPTY`) |
| B-B11 | Deal history can be measured | successful default seven-day window, zero records | PASS (`MEASURED_EMPTY`) |
| B-B12 | Order history can be measured | successful default seven-day window, zero records | PASS (`MEASURED_EMPTY`) |
| B-B13 | Errors cannot become zero | negative tests preserve null counts and `NOT_MEASURED`/`ERROR` | PASS |
| B-B14 | Native write surface is absent | source scan, exact registry, and call-trace tests find zero write calls/tools | PASS |
| B-B15 | Human gate and bounded execution | approval `prompt`; 20 s startup and 30 s tool timeout | PASS |
| B-B16 | Reconciliation remains separate and account-bound | bounded production comparison ran, but the approved audit views expose broker server and internal binding checks without an account identifier comparable to the direct MT5 fingerprint | `EXECUTED_INCOMPLETE` |

The table records the last live observation. The local v2 positive path is
synthetically tested, but B-B16 remains live-incomplete until a separately
approved audit view exposes a trusted, contract-compatible identifier.

## Registration/live read snapshot (before reconciliation)

The configured stdio verifier returned:

```text
mt5_account_get=MEASURED (1)
mt5_positions_get=MEASURED_EMPTY (0)
mt5_orders_get=MEASURED_EMPTY (0)
mt5_history_deals_get=MEASURED_EMPTY (0, default seven-day window)
mt5_history_orders_get=MEASURED_EMPTY (0, default seven-day window)
MCP_WRITE_TOOL_COUNT=0
DIRECT_BROKER_STATE=MEASURED
BROKER_RECONCILIATION=NOT_EXECUTED
```

These zeros are valid only because each direct native call succeeded. They must
not be reused after the observation timestamp or outside the returned history
window.

## Production reconciliation snapshot

A bounded two-way comparison ran on `2026-08-23` through the locally assembled
`AUDIT_DATABASE_URL`. The URL and password were present only in a child
PowerShell/Python process and were not printed or written to the report.

Exact comparison window:

```text
FROM_UTC=2026-08-16T21:19:43.601664+00:00
TO_UTC=2026-08-23T21:19:43.601664+00:00
```

Measured evidence:

```text
DATABASE_MIRROR_STATE=MEASURED
DIRECT_BROKER_STATE=MEASURED
DATABASE_PRODUCTION_MUTATION_COUNT=0
DATABASE_RESULT_TRUNCATED=FALSE

MT5_ACCOUNT_COUNT=1
MT5_CURRENT_POSITION_COUNT=0
MT5_CURRENT_PENDING_ORDER_COUNT=0
MT5_HISTORY_DEAL_COUNT=0
MT5_HISTORY_ORDER_COUNT=0

DATABASE_EXECUTOR_IDENTITY_COUNT=1
DATABASE_EXECUTOR_FRESHNESS_COUNT=1
DATABASE_ACCOUNT_BINDING_COUNT=1
DATABASE_EXECUTION_CONTAINMENT_COUNT=1
DATABASE_EXECUTION_LEDGER_COUNT=0
DATABASE_BROKER_MIRROR_COUNT=0

BROKER_TO_DATABASE_ENTITY_COUNT=0
DATABASE_TO_BROKER_ENTITY_COUNT=0
```

The empty entity sets are measured emptiness for this exact window, not a
permanent broker-zero claim. Both history calls succeeded with the exact
window, both current broker snapshots succeeded, all database reads completed
inside a repeatable-read/read-only transaction, and the transaction had no XID
or changed tuples.

The direct broker server matched exactly one active executor and the database's
internal snapshot/account mismatch counters were clean. Full account binding
is nevertheless not measurable: `wolf15_audit.account_binding_v1` does not
expose `account_id`, `login_hash`, or another identifier that can be compared
with the Native MT5 account fingerprint. No audit view or production database
object was changed to close that gap.

Final result for this observation:

```text
ACCOUNT_BINDING_STATE=INCOMPLETE_ACCOUNT_IDENTIFIER
BROKER_RECONCILIATION=INCOMPLETE_ACCOUNT_IDENTIFIER
B-B16=EXECUTED_INCOMPLETE
EXECUTION_READY=FALSE
PRODUCTION_READY=FALSE
```

This result can become fully account-bound only through a separately reviewed
audit-surface change that exposes a non-reversible, contract-compatible account
binding value. It must not be solved with admin credentials or a broader grant
to application tables.

## Detailed reconciliation sequence

Channel B access is ready, but database/broker reconciliation is a separate,
read-only audit:

1. Select one explicit UTC window and capture Channel A database evidence and
   Channel B broker evidence as close together as possible.
2. Match the Channel B account fingerprint/server to the approved executor and
   account binding. A mismatch is a blocker, not an alternate account to inspect.
3. Reconcile every current broker position and pending order against database
   commands, reports, campaigns, reservations, and broker mirror entities.
4. Reconcile every deal and historical order in the UTC window against the
   execution ledger and expected correlation identifiers.
5. Classify current broker entities as `ACTIVE_ATTRIBUTED`,
   `ACTIVE_UNATTRIBUTED`, or `ACTIVE_AMBIGUOUS`. Age never exempts a current
   position or pending order from exact-one-owner correlation. Only a closed
   historical entity outside the audit window may be `HISTORICAL_PREEXISTING`.
   Preserve `MATCHED`, `ORPHAN`, `UNATTRIBUTED`, and `AMBIGUOUS` for historical
   and database-to-broker evidence where current-state semantics do not apply.
6. Compare both directions: database-to-broker and broker-to-database.
7. Preserve `NOT_MEASURED` for any inaccessible/stale interval, and preserve
   `NOT_EXECUTED` until the comparison actually runs.
8. Only a fully matched, fresh, account-bound window may inform a later readiness
   decision. Channel B itself has no trade authority.

### B-B16 v2 procedure

Run this procedure only after separate authorization confirms that the approved
audit view contains the trusted identifier metadata:

1. Verify both HMAC environment variables are present without printing values.
2. Verify the database URL is the dedicated auditor credential.
3. Start `REPEATABLE READ, READ ONLY` with bounded timeouts.
4. Read only the six approved audit views and record zero-mutation evidence.
5. Invoke exactly the five registered MT5 read tools over one explicit UTC
   window.
6. Require the identifier, exact-case broker server, terminal path fingerprint,
   and terminal build to be identical across all five calls.
7. Require one active, fresh executor and one trusted database identifier with
   the same contract version and `key_id`.
8. Compare full identifiers in constant time and reconcile entities in both
   directions.
9. Roll back the database transaction explicitly and remove temporary reports
   and environment material.

### Stop conditions

```text
HMAC KEY OR KEY_ID MISSING/INVALID       -> NOT_EXECUTED
DATABASE IDENTIFIER ABSENT               -> INCOMPLETE_ACCOUNT_IDENTIFIER
DATABASE IDENTIFIER SOURCE UNTRUSTED     -> EXECUTED_BLOCKED
KEY VERSION MISMATCH                     -> EXECUTED_BLOCKED
BROKER SERVER CASE MISMATCH              -> EXECUTED_BLOCKED
ACCOUNT/PATH/BUILD DRIFT ACROSS CALLS     -> EXECUTED_BLOCKED
ROLE OR READ-ONLY TRANSACTION MISMATCH    -> STOP
VIEW ACCESS DENIED OR QUERY TIMEOUT       -> RECORD + STOP
TRUNCATED OR STALE EVIDENCE               -> NOT_MEASURED
ACTIVE_UNATTRIBUTED/ACTIVE_AMBIGUOUS      -> EXECUTED_BLOCKED
ORPHAN/UNATTRIBUTED/AMBIGUOUS ENTITY      -> EXECUTED_BLOCKED
ANY MUTATION OR BROADER PRIVILEGE NEEDED  -> PROPOSAL ONLY
```

### Process exit contract

The JSON report is always written before a verdict exit. Exit code zero means
only `B-B16=EXECUTED_PASS`; every other outcome is nonzero:

| B-B16/process outcome | Exit code |
| --- | ---: |
| `EXECUTED_PASS` | 0 |
| `EXECUTED_INCOMPLETE` | 2 |
| `EXECUTED_BLOCKED` | 3 |
| `EXECUTION_ERROR` or `NOT_EXECUTED` after collection starts | 4 |
| configuration, usage, or secure-launcher error | 5 |

The PowerShell launcher writes the sanitized child report and propagates the
child exit code without translating a nonzero reconciliation verdict into
success.

Even a live B-B16 pass does not authorize Algo Trading, canary execution, EA
changes, orders, deployment, database mutation, or Gate E approval.

## Verification commands

```powershell
codex mcp get native_mt5_readonly

& 'C:\Users\INTEL\.codex\mcp-envs\native-mt5-readonly\Scripts\python.exe' `
  -m pytest tests\test_native_mt5_readonly_mcp.py -q

& 'C:\Users\INTEL\.codex\mcp-envs\native-mt5-readonly\Scripts\python.exe' `
  -m ops.mt5_mcp.verify --stdio

& '.\.venv\Scripts\python.exe' `
  -m pytest tests\test_mt5_account_binding.py `
            tests\test_channel_b_reconciliation.py -q
```

The production reconciliation launcher obtains only the public endpoint
components from the official Railway CLI, prompts for the auditor password with
hidden input, and removes `AUDIT_DATABASE_URL` when the child process exits:

```powershell
.\scripts\run_channel_b_reconciliation.ps1 `
  -OutputPath (Join-Path $env:TEMP 'wolf15-channel-b-reconciliation.json')
```

Restart Codex after changing MCP configuration. In a new/reloaded task, `/mcp`
should show `native_mt5_readonly`; every direct broker call should still require
the configured prompt approval.

## Disable and rollback

Disable without deleting the entry:

```toml
[mcp_servers.native_mt5_readonly]
enabled = false
```

Remove the Codex registration:

```powershell
codex mcp remove native_mt5_readonly
```

Removing the entry does not change MT5, its active account, broker data, the EA,
or any database row. Delete the isolated environment only as a separate,
explicit cleanup action after the registration has been removed.
