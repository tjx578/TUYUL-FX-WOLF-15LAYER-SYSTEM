# Linux and disposable PostgreSQL preflight

Inventory completed 2026-09-08T20:58:35Z. Current observed checkout HEAD is `7bc5d73cb416e26c40271e5df6d719021164637d`; the parent's original task mentioned 98b72297 and subsequently confirmed the newer commit has the same source tree. This preflight ran no repository tests.

## Independent gates

| Gate | Result | Evidence |
|---|---|---|
| Docker client | AVAILABLE | Docker 29.7.2, context desktop-linux |
| Docker engine | BLOCKED | Server null; dockerDesktopLinuxEngine named pipe missing |
| Existing WSL Linux runner | NOT_AVAILABLE | Only docker-desktop distro, stopped |
| Fresh host capacity | HOLD | Windows CIM reports committed memory 96%; 18,241,560,576 / 18,924,924,928 bytes; available physical memory 4407 MB |
| Dedicated native PG binaries | AVAILABLE_READ_ONLY | PostgreSQL 17.11 postgres/initdb/pg_ctl/psql/pg_isready in C:/Program Files/PostgreSQL/17/bin |
| Native PG service/process | NOT_OBSERVED | No postgres service or running postgres process returned |
| Native disposable cluster | NOT_PROVISIONED | Capacity must be measured freshly below 90% before initialization/start |
| Actual test connection | NOT_BOUND | No server or DSN created |
| Docker image/digest | NOT_RESOLVED | No healthy engine inventory/pull occurred |
| Linux tests | NOT_EXECUTED | Missing Linux engine plus capacity blocker |

Free disk observed: C 5,724,848,128 bytes; D 189,880,721,408 bytes. Physical free RAM does not override the committed-memory guard.

## Native fallback harness

`native_pg_harness.py` is a standard-library-only Windows harness. Its default action is measure. Explicit start requires a fresh Windows GetPerformanceInfo commit ratio strictly below 90%, checks exact PostgreSQL executable SHA256s, rejects preexisting cluster/state and reparse paths, and only then initializes `D:/WOLF15-work/disposable-tests/wolf15-s03-test-20260909`. Capacity is checked again immediately before server start. It never automatically retries.

The planned server binds only 127.0.0.1 at an OS-selected free port, shared_buffers 16MB, max_connections 12, work_mem 1MB, maintenance_work_mem 16MB and max_worker_processes 0. fsync and synchronous_commit remain on. No existing volume, cluster, service, compose project or Docker resource is reused. A successful start creates only the `wolf15_s03_test` fixture database with DISPOSABLE_TEST markers, and verifies server data-directory/host/port/database identity before releasing a fixture-only DSN. There is no actual connection string until this succeeds.

All harness logs, owner state and the non-production fixture password file live in this C staging directory. Child environments do not inherit production connection variables. Explicit stop requires matching owner state, PID, postmaster data directory, port and exact postgres executable identity; it stops only the owned cluster and preserves all files. Stop never requires a capacity PASS: releasing an owned instance remains available at high memory pressure. No deletion or restart command is provided. If startup fails after a server was spawned, the harness attempts read-only PID ownership binding; an unverified process is never blindly killed.

Offline tests cover high/missing capacity, existing cluster preservation, existing owner-state refusal, foreign cluster/PID refusal, and credential-environment isolation. They use mocks and temporary C-only fixture directories; they do not initialize or connect to PostgreSQL. These tests are not a successful real cluster rehearsal.

The one subsequently authorized fresh measurement completed at 2026-09-08T21:03:40.757060Z using Windows GetPerformanceInfo: committed memory 17,940,209,664 / 18,924,924,928 bytes = 94.7967%; available physical memory 4,810,870,784 bytes. The start gate remains HOLD. No initdb or server was started, and no second capacity poll followed. Native PG can supply real PostgreSQL transaction/migration evidence if a later authorized fresh guard passes, but it cannot substitute for Linux runtime evidence.

## Linux execution strategy once independently available

1. Verify a healthy existing engine and fresh host capacity below 90%; do not start/restart Docker from this harness. Inspect existing resources and refuse an occupied `wolf15-s03-test-20260909` name.
2. Resolve exact local/pulled official PostgreSQL 17 and Python 3.11 Linux image digests before use. No digest is invented by this preflight. Pulling approved small runtime images is separate from building application images.
3. Start only a uniquely named, labelled disposable PG container, with an ephemeral tmpfs PGDATA, bounded memory/CPU/process count, and a random host port published only on 127.0.0.1. No production credentials, existing volumes or compose invocation.
4. Materialize the selected reviewed source plus a byte manifest into a dedicated read-only artifact directory. Mount it read-only into a separate disposable Python container; mount only a new evidence directory writable. Verify source hashes inside the runner before and after testing.
5. Give the Python runner the PG container's network namespace, allowing fixture PostgreSQL over its loopback without exposing the Windows native fallback or production networks. Install the unchanged API requirements into a new venv using binary wheels only, record Linux platform/version closure and pip-check. Keep the incompatible MCP2 fixture job in its own environment.
6. Collect exactly the parent-selected tests, then execute them with no repository bytecode/cache writes and explicit XML/temp/evidence paths. Reconcile expected test IDs against actual XML counts, skips and failures. Bind database/schema/role markers to that disposable instance before any destructive fixture migration.
7. Report Linux, native PostgreSQL, local subset, full CI and production evidence separately. Stop only owned disposable resources after ownership verification; do not delete existing resources.

No Docker start/restart, WSL start, native initdb/server start, production connection, provider mutation, repository edit or Git mutation occurred during this preflight.
