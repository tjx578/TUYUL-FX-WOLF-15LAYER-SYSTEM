"""Offline actual-body checks of Demo polling up to command validation.

HTTP, signature verification and ledger calls are doubles; no terminal, broker,
credential or order is accessed. This proves session-local claim suppression.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EA = Path(__file__).resolve().parents[1] / "ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5"
HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(input.source, 'utf8');
const start = source.indexOf('void PollOneDemoCommand()');
const end = source.indexOf('   if(!ValidateDemoCommand(', start);
if (start < 0 || end < start) throw Error('poll body not found');
const body = (source.slice(start, end) + '}')
  .replace('void PollOneDemoCommand()', 'function poll()')
  .replace(/\b(?:string|int) (\w+)/g, 'let $1');
let current;
const events = [];
const ctx = {
  InpExecutorId:'offline', g_last_command_id:input.last || '',
  g_quarantined_command_id:'',
  StringLen:s=>s.length, DemoStateExists:()=>!!input.durable,
  JsonValue:(s,k)=>k==='command_id'?current.id:'fixture',
  HttpRequest:(method)=>{events.push(method);return 200;},
  VerifySignedEnvelope:()=>{events.push('verify');return !!current.valid;},
  AppendLedger:()=>events.push('quarantine'),
};
vm.createContext(ctx);
vm.runInContext(body,ctx,{timeout:1000});
for (const poll of input.polls) {
  current=poll;
  vm.runInContext('poll()',ctx,{timeout:1000});
}
process.stdout.write(JSON.stringify({events,quarantined:ctx.g_quarantined_command_id}));
"""


def _poll(polls: list[dict], **options: object) -> dict:
    node = shutil.which("node")
    assert node is not None, "Node.js required for Demo poll regression checks"
    result = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps({"source": str(EA), "polls": polls, **options}),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_repeated_quarantined_command_is_not_reclaimed() -> None:
    result = _poll([{"id": "bad"}] * 3)
    assert result["events"] == ["GET", "POST", "verify", "quarantine", "GET", "GET"]
    assert result["quarantined"] == "bad"


def test_quarantine_does_not_block_a_different_command() -> None:
    result = _poll([{"id": "bad"}, {"id": "next", "valid": True}])
    assert result["events"] == ["GET", "POST", "verify", "quarantine", "GET", "POST", "verify"]


@pytest.mark.parametrize("options", [{"last": "seen"}, {"durable": True}])
def test_existing_claim_guards_remain_effective(options: dict) -> None:
    assert _poll([{"id": "seen"}], **options)["events"] == ["GET"]


def test_empty_command_is_not_claimed() -> None:
    assert _poll([{"id": ""}])["events"] == ["GET"]
