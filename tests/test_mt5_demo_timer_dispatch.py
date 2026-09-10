"""Offline dispatch checks using the actual MQL OnTimer body in JavaScript.

Only the function declaration and datetime declaration are translated. Calls
outside OnTimer are stubs: these tests prove timer dispatch, not MQL runtime,
broker reconciliation, durable storage, or reporting transport behavior.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DEMO_EA = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Demo.mq5"

HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.source, 'utf8');
const start = source.indexOf('void OnTimer()');
const end = source.indexOf('void OnTick()', start);
if (start < 0 || end < 0) throw new Error('Actual OnTimer body not found');
let timer = source.slice(start, end);
if ((timer.match(/datetime now = TimeCurrent\(\);/g) || []).length !== 1)
  throw new Error('Unexpected MQL declaration: update the explicit translation');
timer = timer.replace('void OnTimer()', 'function OnTimer()')
             .replace('datetime now = TimeCurrent();', 'let now = TimeCurrent();');
const calls = [];
let planIndex = 0;
const context = {
  g_demo_registered: true,
  g_demo_blocked: false,
  g_demo_last_heartbeat: 0,
  g_demo_last_recovery: 0,
  g_trade_event_pending: false,
  g_demo_last_poll: 0,
  InpHeartbeatSeconds: 10,
  InpRecoveryRetrySeconds: 5,
  InpPollIntervalSeconds: 2,
  durableState: true,
  ...input.initial,
  TimeCurrent() { return thisClock; },
  RegisterDemoExecutor() { calls.push('register'); return input.registerResult ?? true; },
  SendDemoHeartbeat() { calls.push('heartbeat'); },
  DemoStateExists() { return context.durableState; },
  RecoverDemoState() {
    calls.push('recover');
    const outcome = (input.recoveryPlan || [])[planIndex++] || {};
    if (outcome.block) context.g_demo_blocked = true;
    if (outcome.clearState) context.durableState = false;
    return outcome.ok ?? false;
  },
  PollOneDemoCommand() { calls.push('poll'); },
  OrderCheck() { throw new Error('Timer reached forbidden OrderCheck'); },
  OrderSend() { throw new Error('Timer reached forbidden OrderSend'); },
};
let thisClock = 0;
vm.createContext(context);
vm.runInContext(timer, context, {timeout: 100});
const observations = [];
for (const tick of input.ticks) {
  thisClock = tick;
  calls.length = 0;
  vm.runInContext('OnTimer()', context, {timeout: 100});
  observations.push({
    calls: [...calls], blocked: context.g_demo_blocked,
    durable: context.durableState, lastRecovery: context.g_demo_last_recovery,
    tradeEvent: context.g_trade_event_pending,
  });
}
process.stdout.write(JSON.stringify(observations));
"""


def _dispatch(**scenario: object) -> list[dict[str, object]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for actual-body cross-language timer dispatch checks")
    result = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps({"source": str(DEMO_EA), **scenario}),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_blocked_command_keeps_recovery_and_heartbeat_running() -> None:
    observed = _dispatch(initial={"g_demo_blocked": True}, ticks=[10, 15])
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == ["recover"]
    assert all(item["blocked"] is True and item["durable"] is True for item in observed)


def test_transient_recovery_failure_then_completion_does_not_unlock_issuance() -> None:
    observed = _dispatch(
        ticks=[10, 11, 15, 20],
        recoveryPlan=[{"block": True}, {"clearState": True, "ok": True}],
    )
    assert [item["calls"] for item in observed] == [["heartbeat", "recover"], [], ["recover"], ["heartbeat"]]
    assert all(item["blocked"] is True for item in observed)
    assert observed[-1]["durable"] is False


def test_blocked_without_durable_state_cannot_claim_new_work() -> None:
    observed = _dispatch(initial={"g_demo_blocked": True, "durableState": False}, ticks=[10, 20])
    assert [item["calls"] for item in observed] == [["heartbeat"], ["heartbeat"]]


def test_pending_recovery_obeys_interval_and_suppresses_poll_even_when_not_due() -> None:
    observed = _dispatch(initial={"g_demo_blocked": True, "g_demo_last_recovery": 10}, ticks=[11, 14, 15])
    assert [item["calls"] for item in observed] == [["heartbeat"], [], ["recover"]]
    assert observed[-1]["lastRecovery"] == 15


def test_trade_event_requests_recovery_before_interval_then_resets_event() -> None:
    observed = _dispatch(
        initial={"g_demo_blocked": True, "g_demo_last_recovery": 10, "g_trade_event_pending": True},
        ticks=[11, 12],
    )
    assert [item["calls"] for item in observed] == [["heartbeat", "recover"], []]
    assert observed[0]["lastRecovery"] == 11
    assert observed[0]["tradeEvent"] is False


def test_terminal_clear_cannot_fall_through_to_poll_in_same_tick() -> None:
    observed = _dispatch(ticks=[10, 11], recoveryPlan=[{"clearState": True, "ok": True}])
    assert observed[0]["calls"] == ["heartbeat", "recover"]
    assert observed[1]["calls"] == ["poll"]


@pytest.mark.parametrize("register_result", [True, False])
def test_registration_return_still_precedes_recovery(register_result: bool) -> None:
    observed = _dispatch(
        initial={"g_demo_registered": False, "g_demo_blocked": True},
        registerResult=register_result,
        ticks=[10, 15],
    )
    assert observed[0]["calls"] == ["register"]
    assert observed[1]["calls"] == (["heartbeat", "recover"] if register_result else ["register"])


def test_unblocked_empty_executor_still_polls() -> None:
    observed = _dispatch(initial={"durableState": False}, ticks=[10])
    assert observed[0]["calls"] == ["heartbeat", "poll"]


def test_recovery_and_timer_have_no_submit_primitive_or_automatic_unblock() -> None:
    source = DEMO_EA.read_text(encoding="utf-8")
    recovery = source[source.index("bool RecoverDemoState()") : source.index("int OnInit()")]
    timer = source[source.index("void OnTimer()") : source.index("void OnTick()")]
    for body in (recovery, timer):
        assert "OrderSend(" not in body
        assert "OrderCheck(" not in body
        assert "g_demo_blocked = false" not in body
