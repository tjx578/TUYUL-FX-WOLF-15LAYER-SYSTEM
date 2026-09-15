# Standalone orchestrator acceptance traceability

Statuses describe the resulting repository tree. `PASS` requires an identified
test or inspection; `PLANNED_RUNTIME` means it must remain `NOT_EXECUTED` until
a separately authorized rollout. Historical receipts are supporting evidence,
not inherited proof for a changed tree.

## Source and local acceptance (T01-T15)

| ID | Requirement | Repository evidence / final gate | Status |
| --- | --- | --- | --- |
| T01 | API and orchestrator have one explicit owner boundary | `api/app_factory.py`, ownership tests, service docs | MAPPED; final tests required |
| T02 | API cannot enable embedded orchestration | API factory and both API start-script rejection tests | MAPPED; final tests required |
| T03 | Standalone startup owns one foreground lifecycle | `start_orchestrator.sh`, `state_manager.py`, entrypoint smoke | MAPPED; T14 smoke required |
| T04 | Orchestrator remains coordination/compliance-only | ownership map, API/orchestrator README, static ownership tests | MAPPED; final tests required |
| T05 | Missing/false/true legacy flag behavior is fail-closed | `test_orchestrator_runtime_ownership.py` | EXISTING EVIDENCE; rerun on resulting tree |
| T06 | Dedicated manifest/script/module resolve exactly | manifest and static entrypoint checks | EXISTING EVIDENCE; T14 smoke required |
| T07 | At most one effective writer | Redis lease/fence unit and integration tests | EXISTING EVIDENCE; rerun required |
| T08 | Stale owner cannot mutate guarded state | fencing tests and disposable Redis probe | EXISTING EVIDENCE; rerun required |
| T09 | Committed state/watermark hydrate across process restart | recovery contract plus `tests/integration/test_orchestrator_process_recovery.py` using distinct OS processes and disposable Redis | IMPLEMENTATION/TEST GATE |
| T10 | Health distinguishes liveness, standby, owner, and fatal/stall | supervisor/health tests | EXISTING EVIDENCE; rerun required |
| T11 | Shutdown settles/cancels inflight work and restart is idempotent | graceful-shutdown and recovery integration tests | IMPLEMENTATION/TEST GATE |
| T12 | Supervisor transitions and stagnation are observable | `test_orchestrator_supervisor.py`, state-manager tests | EXISTING EVIDENCE; rerun required |
| T13 | API projection worker remains non-orchestration | `TradeOutboxWorker` ownership/process-scope tests | MAPPED; final tests required |
| T14 | Exact images use effective API-only and orchestrator entrypoints | disposable API/orchestrator image smoke receipt | NOT_EXECUTED until final local smoke |
| T15 | Cutover/rollback preserves single ownership and safety | `orchestrator-cutover.md`, static config checks | DOCUMENTED; runtime proof is R01-R08 |

No `PARTIAL` or `UNVERIFIED` label is hidden: open local gates are explicitly
T09, T11, and T14. All source gates must be rerun against the final tree.

The opt-in process-recovery test exercises committed state after graceful
shutdown and abrupt process exit before an in-memory change is committed. It
uses the real lifecycle, Redis lease/fence scripts, and hydration code. Receipts
include distinct worker PIDs, generations, revisions, and cleanup. Its local
Redis remains running across the two processes; it does not establish Redis
server-loss recovery, production durability, or downstream execution replay.
Historical same-process unit tests remain supporting logic coverage and must
not be described as separate-process observations.

## Runtime acceptance (R01-R08)

| ID | Runtime observation | Required evidence | Current status |
| --- | --- | --- | --- |
| R01 | Exact deployed source/image and effective config | provider deployment/image/config receipt | NOT_EXECUTED |
| R02 | API has no embedded compliance tick | logs, process inventory, API behavior | NOT_EXECUTED |
| R03 | Exactly one standalone owner; overlap is standby-only | owner/generation heartbeats across replicas | NOT_EXECUTED |
| R04 | Stale predecessor writes are rejected | fenced-write observations during controlled takeover | NOT_EXECUTED |
| R05 | State/watermark recover after restart without replay | pre/post restart state and effect ledger | NOT_EXECUTED |
| R06 | Health/readiness reflect owner, standby, fatal, and stall | endpoint and supervisor observations | NOT_EXECUTED |
| R07 | Rollback restores exactly one bound predecessor | exact rollback deployment and namespace receipt | NOT_EXECUTED |
| R08 | Execution remains contained with zero broker effects | flags, kill switch, queues/commands/reservations/outboxes and broker-effect receipt | NOT_EXECUTED |

These gates are deliberately not satisfiable by source review. Failure to run
them is not converted into PASS, and this matrix grants no deployment or
execution authority.
