# P2 — Clock contract audit (no code change yet)

**Branch:** `fix/d0-demo-monotonic-scheduler-clock`
**Base:** `6c93d4430f3b6a3fece63c609dbea52ec4692dfd` (exact `origin/main`, not stacked on P1)
**Question P2 must answer, and only this:** does the D0 scheduler stay alive on
elapsed time without changing broker-time semantics and without widening
execution authority?

---

## 1. Complete clock inventory

Every clock primitive in `Wolf15_DumbExecutor_Demo.mq5`. The surface is small —
**three call sites**, and only one of them is a scheduler.

| Line | Expression | Class needed | Current primitive | Verdict |
|---:|---|---|---|---|
| 1229 | `datetime now = TimeCurrent();` | **scheduler / elapsed** | quote time | **DEFECT — fix** |
| 507 | `if(expiry <= 0 \|\| TimeGMT() >= expiry)` | broker / UTC semantic | `TimeGMT()` | **CORRECT — keep** |
| 778 | `HistorySelect(issued - 300, TimeCurrent() + 60)` | broker / server time | quote time | **CANDIDATE — see §4** |

Scheduler state, all derived from the single `now` at line 1229:

| Line | Consumer | Interval input | Class |
|---:|---|---|---|
| 1235 / 1238 | `SendDemoHeartbeat()` | `InpHeartbeatSeconds` (10) | elapsed |
| 1243 / 1246 | `RecoverDemoState()` | `InpRecoveryRetrySeconds` (5) | elapsed |
| 1253 / 1256 | `PollOneDemoCommand()` | `InpPollIntervalSeconds` (2) | elapsed |

Declared at `Wolf15_DumbExecutor_Demo.mq5:64-67`, type `datetime`, initialised `0`.

## 2. Why line 1229 is the defect

`EventSetTimer(1)` is installed at `OnInit` (line 1221), so `OnTimer` fires every
second regardless of market activity. But on a timer event `TimeCurrent()`
returns the time of the **last quote in Market Watch**. With no new quote —
weekend, market close, feed disconnect, illiquid symbol — `TimeCurrent()` stops
advancing while `OnTimer` keeps firing. Every `now - g_demo_last_*` comparison
then stays frozen below its threshold.

Result: **heartbeat, recovery retry, and command polling all stall together**,
precisely in the disconnect scenario where recovery must keep retrying. The
scheduler is coupled to quote movement, which is not what any of the three
intervals means.

## 3. Containment — verified, not assumed

The three scheduler variables are **in-memory only**:

- Not fields of `struct DemoExecutionState`
- Not part of `DemoStateMaterial()`, the string fed to the HMAC integrity tag

So changing their type and unit touches **no durable state, no integrity tag, no
wire contract, no schema**. The blast radius of P2 is the timer body plus three
global declarations.

## 4. The one genuinely arguable site — line 778

```cpp
if(!HistorySelect(issued - 300, TimeCurrent() + 60))
```

This selects broker history, which is indexed in **server time**, so a monotonic
tick counter would be wrong here — the class is correct. The problem is narrower:
if `TimeCurrent()` is stale, the window end `TimeCurrent() + 60` can fall
**before a deal that just executed**, so reconciliation can miss the very deal it
is trying to reconcile. Same root cause, different failure.

`TimeTradeServer()` returns the *calculated* current trade-server time and keeps
advancing without a new quote, so it is the correct "now, in server time"
primitive. Class unchanged, staleness removed.

Recommended: `TimeCurrent()` -> `TimeTradeServer()` at line 778 only. Flagged
rather than assumed, because it touches the reconciliation read path.

## 5. Second finding — the interval inputs are unvalidated in the DEMO artifact

`InpPollIntervalSeconds`, `InpHeartbeatSeconds` and `InpRecoveryRetrySeconds` are
declared in `Wolf15_DumbExecutor_Shadow.mq5:18-21`, not in the Demo file.

Shadow's `OnInit` validates one of them (`InpRecoveryRetrySeconds < 1`,
`Shadow.mq5:1756`) — but the Demo build renames Shadow's `OnInit` to
`W15ShadowTransportOnInitUnused` (`Demo.mq5:13`), so **that validation never runs
in the DEMO artifact**, and Demo's own `OnInit` does not replace it.

A zero or negative interval therefore reaches the scheduler unchecked. That is
acceptance item **D** ("poll not due -> must not poll early") failing today,
independent of the clock source. It belongs in P2.

## 6. Structural finding — Demo compiles Shadow into itself

`Demo.mq5:13-27` `#define`s Shadow's five event handlers to `*Unused` names,
`#include`s `Wolf15_DumbExecutor_Shadow.mq5`, then `#undef`s them. One
compilation unit holds **two** `OnTimer` bodies; only Demo's is live.

Shadow's own timer carries the **identical defect**:

```cpp
Wolf15_DumbExecutor_Shadow.mq5:1833:   datetime now = TimeCurrent();
```

feeding `g_last_heartbeat` / `g_last_recovery` / `g_last_poll` at lines 1839,
1848, 1856. Dead in the DEMO artifact — **live in the SHADOW artifact**, which is
what P8 rehearses on.

Other Shadow clock uses, checked and benign:

| Line | Use | Assessment |
|---:|---|---|
| 123 | `GetTickCount()` as PRNG seed | fine |
| 734 / 739 | `GetTickCount() - started_ms` elapsed | wrap-safe via unsigned arithmetic |
| 99, 1368, 1440 | `TimeGMT()` for stamps and expiry | correct class |

## 7. Rollover (acceptance item G)

`GetTickCount()` is 32-bit milliseconds and wraps after ~49.7 days — a real
concern for an EA meant to run continuously. `GetTickCount64()` is 64-bit
milliseconds and does not wrap on any realistic horizon.

**Use `GetTickCount64()`.** This retires item G by primitive choice rather than by
wrap-handling arithmetic. Interval inputs are in seconds, so comparisons become
`(ulong)interval * 1000`, and the three globals change `datetime` -> `ulong`.
`EventSetTimer(1)` gives 1-second granularity, so millisecond precision is ample.

## 8. Proposed classification — final

| Call site | Keep | Change to | Reason |
|---|---|---|---|
| `Demo.mq5:1229` scheduler `now` | no | `GetTickCount64()` | elapsed time must not depend on quotes |
| `Demo.mq5:1235/1243/1253` comparisons | no | ms thresholds | unit follows the primitive |
| `Demo.mq5:64-66` globals | no | `ulong` | unit follows the primitive |
| `Demo.mq5:507` expiry | **yes** | — | command validity is a UTC contract |
| `Demo.mq5:778` history window | no | `TimeTradeServer()` | still server time, but advances without quotes |
| Demo `OnInit` interval validation | — | **add** | acceptance item D is unenforced today |
| Ordering register -> heartbeat -> recovery -> blocked -> poll | **yes** | — | must not change |
| `OrderSend` / `OrderCheck` call sites | **yes** | — | out of scope |
| Strategy / risk semantics | **yes** | — | out of scope |

Not touched: credential pipe #446, Channel B, database, Alembic, RR, TP, risk,
SSOT, symbol policy, reconciliation model, README, Railway.

## 9. Owner decision — locked 2026-09-11

```
P2_SCOPE              = DEMO + SHADOW
P2B_LATER             = CANCELLED
SCHEDULER_CLOCK       = GetTickCount64
SERVER_HISTORY_CLOCK  = TimeTradeServer
COMMAND_EXPIRY_CLOCK  = TimeGMT - unchanged
DURABLE_STATE_SCHEMA  = unchanged
WIRE_CONTRACT         = unchanged
ORDERSEND_AUTHORITY   = unchanged
HISTORICAL_SHADOW     = preserved, not final attestation
P8                    = fresh rebind/rehearsal required
```

Option B was chosen: fix both artifacts in this branch. P8 mandates a fresh
exact-SHA SHADOW rehearsal regardless, so the Shadow hash has to be re-bound
anyway; splitting an identical defect into P2 and P2b would add a branch,
review, compile and regression cycle without reducing final acceptance work.
Historical SHADOW evidence stays valid *for the artifact it was taken on* — it
simply cannot serve as final attestation, which was already true.

## 10. Clock semantics, stated precisely

```
TimeCurrent()      = last-known quote / server timestamp
TimeTradeServer()  = client-calculated estimate of current server time
GetTickCount64()   = elapsed scheduler clock, 64-bit ms, no practical wrap
TimeGMT()          = UTC wall clock
```

`TimeTradeServer()` is a terminal-side estimate that depends on the client
clock. It is right for a `HistorySelect` window bound, which only needs a
server-time-domain value that keeps moving. It is **not** broker-event truth:
final deal timing evidence must come from the order/deal timestamps in broker
history, not from this call.

## 11. What was implemented

Three files. Nothing else in the repository was touched.

| File | Change |
|---|---|
| `Wolf15_DumbExecutor_Shadow.mq5` | scheduler globals -> `ulong *_ms`; `OnTimer` -> `GetTickCount64()`; added shared `ValidateSchedulerIntervals()`; `OnInit` single-interval check replaced by the shared helper |
| `Wolf15_DumbExecutor_Demo.mq5` | scheduler globals -> `ulong *_ms`; `OnTimer` -> `GetTickCount64()`; `OnInit` now calls the shared helper; `HistorySelect` upper bound -> `TimeTradeServer()` |
| `tests/test_mt5_demo_timer_dispatch.py` | harness translation updated to the real new body and generalised to drive both EAs; scenarios converted to ms; `TimeCurrent()` wired to throw; gates A/B/C/D/E/F/G/J/K/L added |

Globals are renamed to `_ms`, not merely retyped, so a later reader cannot mix a
`datetime` with monotonic milliseconds.

`ValidateSchedulerIntervals()` lives in the Shadow file because the Demo build
`#include`s it, so both active `OnInit` handlers call one implementation and the
contract cannot drift between artifacts.

Dispatch ordering is byte-for-byte preserved in both timers:
`register -> heartbeat -> recovery (if pending) -> blocked check -> poll`.

## 12. Acceptance

| Gate | Requirement | Result |
|---|---|---|
| A | quote time frozen -> Demo heartbeat still due | PASS |
| B | quote time frozen -> Demo recovery still due | PASS |
| C | quote time frozen -> Demo polling still due | PASS |
| D | interval `<= 0` -> `INIT_PARAMETERS_INCORRECT` in **both** artifacts | PASS (source contract) |
| E | durable state -> recovery still precedes polling | PASS |
| F | blocked latch -> new issuance still 0 | PASS |
| G | elapsed clock is `GetTickCount64`, not the 32-bit counter | PASS |
| H | `OrderCheck` call sites/count unchanged | PASS — Demo 1/1, Shadow 0/0 |
| I | `OrderSend` unchanged; Demo max-one, Shadow zero | PASS — Demo 1/1, Shadow 0/0 |
| J | command/wire/risk/strategy/durable-state material unchanged | PASS — no diff line touches them |
| K | Shadow with quote frozen -> cadence still advances | PASS |
| L | `HistorySelect` bound independent of stale quote time | PASS |
| M | MetaEditor compile Demo + Shadow = 0 errors | **NOT RUN** — no MetaEditor on this host |
| N | existing D0 + Shadow regression suites | PASS — 455 passed (was 446) |

Gates A/B/C/K are proved by construction, not only by assertion: `TimeCurrent()`
is wired to **throw** inside the harness context, so any dispatch reaching a stub
at all demonstrates the cadence does not read quote time.

The harness was verified in both directions. Reverting the Demo timer to
`datetime now_ms = TimeCurrent();` makes it refuse — 3 failures including
`Unexpected MQL declaration: update the explicit translation` — so the tests are
bound to the actual timer body and cannot be satisfied by a stale simulation.

**Gate M is the one open item.** It needs MetaEditor and belongs with P6, where
the MQ5 -> EX5 hashes are bound. Until then P2 is source-verified, not
compile-verified.
