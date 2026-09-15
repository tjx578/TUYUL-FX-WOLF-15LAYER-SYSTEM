"""Offline dispatch checks using the actual MQL OnTimer bodies in JavaScript.

The Demo and Shadow timers are structurally identical, so one harness drives
both. Only the function declaration, the elapsed-clock declaration, and the MQL
cast/integer-suffix spellings are translated. Calls outside OnTimer are stubs:
these tests prove timer dispatch, not MQL runtime, broker reconciliation,
durable storage, or reporting transport behavior.

Scheduler times are elapsed milliseconds from GetTickCount64(), not wall clock.
Scenarios are written in seconds and converted by ``_ms`` so they stay readable.

TimeCurrent() is deliberately wired to throw inside the timer context. It is the
last known quote time and stops advancing when quotes stop, so a scheduler that
reads it stalls exactly during a disconnect. The throwing stub is what proves
the timers no longer depend on quote movement.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EA_DIR = ROOT / "ea_interface" / "wolf15_executor"
DEMO_EA = EA_DIR / "Wolf15_DumbExecutor_Demo.mq5"
SHADOW_EA = EA_DIR / "Wolf15_DumbExecutor_Shadow.mq5"

DEMO_NAMES = {
    "registered": "g_demo_registered",
    "blocked": "g_demo_blocked",
    "heartbeatMs": "g_demo_last_heartbeat_ms",
    "recoveryMs": "g_demo_last_recovery_ms",
    "pollMs": "g_demo_last_poll_ms",
    "tradeEvent": "g_trade_event_pending",
    "register": "RegisterDemoExecutor",
    "heartbeat": "SendDemoHeartbeat",
    "stateExists": "DemoStateExists",
    "recover": "RecoverDemoState",
    "poll": "PollOneDemoCommand",
}

SHADOW_NAMES = {
    "registered": "g_registered",
    "blocked": "g_recovery_blocked",
    "heartbeatMs": "g_last_heartbeat_ms",
    "recoveryMs": "g_last_recovery_ms",
    "pollMs": "g_last_poll_ms",
    "tradeEvent": None,
    "register": "RegisterExecutor",
    "heartbeat": "SendHeartbeat",
    "stateExists": "PendingReportExists",
    "recover": "RecoverPendingReport",
    "poll": "PollOneCommand",
}

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const N = input.names;
const source = fs.readFileSync(input.source, 'utf8');
const start = source.indexOf('void OnTimer()');
const end = source.indexOf('void OnTick()', start);
if (start < 0 || end < 0) throw new Error('Actual OnTimer body not found');
let timer = source.slice(start, end);
if ((timer.match(/const ulong now_ms = GetTickCount64\(\);/g) || []).length !== 1)
  throw new Error('Unexpected MQL declaration: update the explicit translation');
if (/TimeCurrent\s*\(/.test(timer))
  throw new Error('Scheduler must not read quote time');
timer = timer.replace('void OnTimer()', 'function OnTimer()')
             .replace('const ulong now_ms = GetTickCount64();', 'let now_ms = GetTickCount64();')
             .replace(/\(ulong\)/g, '')
             .replace(/(\d+)ULL\b/g, '$1');
const calls = [];
let planIndex = 0;
let elapsedMs = 0;
let pendingState = true;
const context = {
  InpHeartbeatSeconds: 10,
  InpRecoveryRetrySeconds: 5,
  InpPollIntervalSeconds: 2,
  GetTickCount64() { return elapsedMs; },
  TimeCurrent() { throw new Error('Timer read quote time'); },
  OrderCheck() { throw new Error('Timer reached forbidden OrderCheck'); },
  OrderSend() { throw new Error('Timer reached forbidden OrderSend'); },
};
context[N.registered] = true;
context[N.blocked] = false;
context[N.heartbeatMs] = 0;
context[N.recoveryMs] = 0;
context[N.pollMs] = 0;
if (N.tradeEvent) context[N.tradeEvent] = false;
context[N.register] = function () { calls.push('register'); return input.registerResult ?? true; };
context[N.heartbeat] = function () { calls.push('heartbeat'); };
context[N.stateExists] = function () { return pendingState; };
context[N.recover] = function () {
  calls.push('recover');
  const outcome = (input.recoveryPlan || [])[planIndex++] || {};
  if (outcome.block) context[N.blocked] = true;
  if (outcome.clearState) pendingState = false;
  return outcome.ok ?? false;
};
context[N.poll] = function () { calls.push('poll'); };
const initial = input.initial || {};
if ('durableState' in initial) pendingState = initial.durableState;
for (const [key, value] of Object.entries(initial)) {
  if (key !== 'durableState') context[key] = value;
}
vm.createContext(context);
vm.runInContext(timer, context, {timeout: 100});
const observations = [];
for (const tick of input.ticks) {
  elapsedMs = tick;
  calls.length = 0;
  vm.runInContext('OnTimer()', context, {timeout: 100});
  observations.push({
    calls: [...calls], blocked: context[N.blocked],
    durable: pendingState, lastRecovery: context[N.recoveryMs],
    tradeEvent: N.tradeEvent ? context[N.tradeEvent] : null,
  });
}
process.stdout.write(JSON.stringify(observations));
"""


def _ms(*seconds: float) -> list[int]:
    """Scenario times are written in seconds; the scheduler clock is milliseconds."""
    return [int(value * 1000) for value in seconds]


def _dispatch(source: Path = DEMO_EA, names: dict[str, str | None] | None = None, **scenario: object):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for actual-body cross-language timer dispatch checks")
    result = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps({"source": str(source), "names": names or DEMO_NAMES, **scenario}),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _shadow_dispatch(**scenario: object):
    return _dispatch(source=SHADOW_EA, names=SHADOW_NAMES, **scenario)


# --- Demo dispatch behavior: unchanged intent, milliseconds -------------------


def test_blocked_command_keeps_recovery_and_heartbeat_running() -> None:
    observed = _dispatch(initial={"g_demo_blocked": True}, ticks=_ms(10, 15))
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == ["recover"]
    assert all(item["blocked"] is True and item["durable"] is True for item in observed)


def test_transient_recovery_failure_then_completion_does_not_unlock_issuance() -> None:
    observed = _dispatch(
        ticks=_ms(10, 11, 15, 20),
        recoveryPlan=[{"block": True}, {"clearState": True, "ok": True}],
    )
    assert [item["calls"] for item in observed] == [["heartbeat", "recover"], [], ["recover"], ["heartbeat"]]
    assert all(item["blocked"] is True for item in observed)
    assert observed[-1]["durable"] is False


def test_blocked_without_durable_state_cannot_claim_new_work() -> None:
    observed = _dispatch(initial={"g_demo_blocked": True, "durableState": False}, ticks=_ms(10, 20))
    assert [item["calls"] for item in observed] == [["heartbeat"], ["heartbeat"]]


def test_pending_recovery_obeys_interval_and_suppresses_poll_even_when_not_due() -> None:
    observed = _dispatch(
        initial={"g_demo_blocked": True, "g_demo_last_recovery_ms": 10_000},
        ticks=_ms(11, 14, 15),
    )
    assert [item["calls"] for item in observed] == [["heartbeat"], [], ["recover"]]
    assert observed[-1]["lastRecovery"] == 15_000


def test_trade_event_requests_recovery_before_interval_then_resets_event() -> None:
    observed = _dispatch(
        initial={
            "g_demo_blocked": True,
            "g_demo_last_recovery_ms": 10_000,
            "g_trade_event_pending": True,
        },
        ticks=_ms(11, 12),
    )
    assert [item["calls"] for item in observed] == [["heartbeat", "recover"], []]
    assert observed[0]["lastRecovery"] == 11_000
    assert observed[0]["tradeEvent"] is False


def test_terminal_clear_cannot_fall_through_to_poll_in_same_tick() -> None:
    observed = _dispatch(ticks=_ms(10, 11), recoveryPlan=[{"clearState": True, "ok": True}])
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == ["poll"]


@pytest.mark.parametrize("register_result", [True, False])
def test_registration_return_still_precedes_recovery(register_result: bool) -> None:
    observed = _dispatch(
        initial={"g_demo_registered": False, "g_demo_blocked": True},
        registerResult=register_result,
        ticks=_ms(10, 15),
    )
    assert observed[0]["calls"] == ["register"]
    assert observed[1]["calls"] == (["heartbeat", "recover"] if register_result else ["register"])


def test_unblocked_empty_executor_still_polls() -> None:
    observed = _dispatch(initial={"durableState": False}, ticks=_ms(10))
    assert observed[0]["calls"] == ["heartbeat", "poll"]


def test_recovery_and_timer_have_no_submit_primitive_or_automatic_unblock() -> None:
    source = DEMO_EA.read_text(encoding="utf-8")
    recovery = source[source.index("bool RecoverDemoState()") : source.index("int OnInit()")]
    timer = source[source.index("void OnTimer()") : source.index("void OnTick()")]
    for body in (recovery, timer):
        assert "OrderSend(" not in body
        assert "OrderCheck(" not in body
        assert "g_demo_blocked = false" not in body


# --- Gates A, B, C, E, F, K: cadence survives a frozen quote feed -------------


def test_demo_scheduler_advances_while_quote_time_is_frozen() -> None:
    """Gates A and C.

    TimeCurrent() throws in the harness context, so reaching any dispatch at all
    proves the cadence is driven by elapsed time, not by quote movement.
    """
    observed = _dispatch(initial={"durableState": False}, ticks=_ms(10, 12, 20, 30))
    assert observed[0]["calls"] == ["heartbeat", "poll"]
    assert observed[1]["calls"] == ["poll"]
    assert observed[2]["calls"] == ["heartbeat", "poll"]
    assert observed[3]["calls"] == ["heartbeat", "poll"]


def test_demo_recovery_retry_advances_while_quote_time_is_frozen() -> None:
    """Gate B: recovery must keep retrying during a disconnect.

    Recovery fires on every 5s boundary and heartbeat on every 10s boundary,
    driven purely by elapsed time.
    """
    observed = _dispatch(ticks=_ms(5, 10, 15, 20))
    assert [item["calls"] for item in observed] == [
        ["recover"],
        ["heartbeat", "recover"],
        ["recover"],
        ["heartbeat", "recover"],
    ]


def test_shadow_scheduler_advances_while_quote_time_is_frozen() -> None:
    """Gate K: the SHADOW artifact carries its own live timer."""
    observed = _shadow_dispatch(initial={"durableState": False}, ticks=_ms(10, 12, 20))
    assert observed[0]["calls"] == ["heartbeat", "poll"]
    assert observed[1]["calls"] == ["poll"]
    assert observed[2]["calls"] == ["heartbeat", "poll"]


def test_shadow_pending_report_recovery_precedes_polling() -> None:
    """Gate E for the SHADOW artifact: ordering is unchanged by the clock swap."""
    observed = _shadow_dispatch(ticks=_ms(10, 15))
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == ["recover"]
    assert all(item["durable"] is True for item in observed)


def test_shadow_recovery_block_latches_and_stops_polling() -> None:
    """Gate F for the SHADOW artifact."""
    observed = _shadow_dispatch(ticks=_ms(10, 15), recoveryPlan=[{"block": True}])
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == []
    assert all(item["blocked"] is True for item in observed)


# --- Gates D, G, J, L: source contract ---------------------------------------


def test_both_artifacts_use_a_non_wrapping_elapsed_clock() -> None:
    """Gate G: GetTickCount64, never the 32-bit counter that wraps at ~49.7 days."""
    for path in (DEMO_EA, SHADOW_EA):
        source = path.read_text(encoding="utf-8")
        timer = source[source.index("void OnTimer()") : source.index("void OnTick()")]
        assert "const ulong now_ms = GetTickCount64();" in timer
        assert "TimeCurrent(" not in timer
        assert not re.search(r"\bGetTickCount\s*\(", timer)


def test_both_active_on_init_handlers_validate_scheduler_intervals() -> None:
    """Gate D.

    The Demo build renames this shared file's OnInit to *Unused, so a check
    living only there would never run in the DEMO artifact.
    """
    shadow = SHADOW_EA.read_text(encoding="utf-8")
    demo = DEMO_EA.read_text(encoding="utf-8")

    helper = shadow[shadow.index("bool ValidateSchedulerIntervals()") : shadow.index("struct PendingReportState")]
    assert "InpPollIntervalSeconds < 1" in helper
    assert "InpHeartbeatSeconds < 1" in helper
    assert "InpRecoveryRetrySeconds < 1" in helper
    assert "return false;" in helper

    for source in (shadow, demo):
        on_init = source[source.index("int OnInit()") : source.index("void OnTimer()")]
        assert "if(!ValidateSchedulerIntervals())" in on_init
        assert "return INIT_PARAMETERS_INCORRECT;" in on_init


def test_reconciliation_history_window_does_not_depend_on_stale_quote_time() -> None:
    """Gate L.

    HistorySelect indexes broker history by server time, so the upper bound must
    stay in the server-time domain -- but it has to keep advancing when quotes
    stop, or a deal that just executed can fall outside the window.
    """
    demo = DEMO_EA.read_text(encoding="utf-8")
    assert "HistorySelect(issued - 300, TimeTradeServer() + 60)" in demo
    assert "TimeCurrent(" not in demo


def test_command_expiry_still_uses_utc_wall_clock() -> None:
    """Gate J guard: expiry is a contract with the issuer, not an elapsed interval."""
    demo = DEMO_EA.read_text(encoding="utf-8")
    assert "if(expiry <= 0 || TimeGMT() >= expiry)" in demo
