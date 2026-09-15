"""Execute the actual MQL5 frame-reading body with deterministic I/O doubles.

No pipe, vault, broker, HTTP, or MT5 is opened. This is cross-language regression
coverage, not proof of native MQL5 pipe behavior or runtime acceptance.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "ea_interface/wolf15_executor/Wolf15_DumbExecutor_Shadow.mq5"
HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(scenario.source, 'utf8');
let start = source.indexOf('bool LoadRuntimeCredentials(');
let frame = source.slice(start, source.indexOf('   string payload_json =', start));
frame += 'return {payload: payload, reason: reason};\n}';
let helper = '';
start = source.indexOf('uint ReadCredentialBytes(');
if (start >= 0) helper = source.slice(start, source.indexOf('//+---', start));
function translate(s) {
  return s
    .replace(/uint ReadCredentialBytes\([^)]*\)/, 'function ReadCredentialBytes(handle, buffer, expected, deadline)')
    .replace(/bool LoadRuntimeCredentials\(string &reason\)/, 'function LoadRuntimeCredentials()')
    .replace(/uchar (\w+)\[\];/g, 'let $1 = [];')
    .replace(/\b(?:const )?(?:uint|ulong|int|ushort|string) (\w+)/g, 'let $1')
    .replace(/\((?:uint|ulong|int)\)/g, '')
    .replace(/\b(\d+)ULL\b/g, '$1')
    .replace(/'0'/g, '48').replace(/'9'/g, '57');
}
function numericDefine(name) {
  const match = source.match(new RegExp('#define ' + name + ' (\\d+)'));
  if (!match) throw Error('missing numeric constant: ' + name);
  return Number(match[1]);
}
let now = 0, closed = 0, opened = 0, readCalls = 0, error = 0;
let chunks = scenario.chunks.map(c => ({at:c.at, bytes:[...Buffer.from(c.text, 'ascii')]}));
const context = {
  reason: '',
  InpCredentialPipePath: '\\\\.\\pipe\\offline-only',
  InpExecutorId:'fixture', InpExpectedAccountReferenceSha256:'a'.repeat(64),
  InpCommandVerificationKeyId:'fixture', INVALID_HANDLE:-1,
  FILE_READ:1, FILE_BIN:2, FILE_ANSI:4, CP_UTF8:65001,
  W15_CREDENTIAL_HEADER_BYTES:numericDefine('W15_CREDENTIAL_HEADER_BYTES'),
  W15_CREDENTIAL_MAX_BYTES:numericDefine('W15_CREDENTIAL_MAX_BYTES'),
  W15_CREDENTIAL_READ_TIMEOUT_MS:numericDefine('W15_CREDENTIAL_READ_TIMEOUT_MS'),
  W15_CREDENTIAL_READ_RETRY_MS:numericDefine('W15_CREDENTIAL_READ_RETRY_MS'),
  ClearRuntimeCredentials:()=>{}, StringFind:(s,v)=>s.indexOf(v),
  IsSafeWireIdentifier:()=>true, IsLowerHexExact:()=>true,
  ResetLastError:()=>{error=0;}, GetLastError:()=>error,
  ERR_FILE_ENDOFFILE:5027,
  FileOpen:()=>{opened++; return scenario.openFails ? -1 : 7;},
  FileClose:()=>{closed++;}, ArrayResize:(a,n)=>{a.length=n; return n;},
  GetTickCount64:()=>now, Sleep:ms=>{now+=ms;},
  IsStopped:()=>scenario.stopAt !== undefined && now>=scenario.stopAt,
  FileReadArray:(h,a,offset,count)=>{
    if (++readCalls > 2000) throw Error('unbounded read loop');
    now += (scenario.readDurations || [])[readCalls-1] || 0;
    if(scenario.readError || readCalls === scenario.errorAtRead){error=scenario.readError || 5001;return 0;}
    const c=chunks.find(c=>c.at<=now && c.bytes.length);
    if(!c){error=5027;return 0;}
    const data=c.bytes.splice(0,count);
    data.forEach((v,i)=>a[offset+i]=v);
    return data.length;
  },
  CharArrayToString:(a,start,n)=>Buffer.from(a.slice(start,start+n)).toString('ascii'),
  StringGetCharacter:(s,i)=>s.charCodeAt(i), StringToInteger:s=>parseInt(s,10),
};
vm.createContext(context);
vm.runInContext(translate(helper)+translate(frame),context,{timeout:1000});
const result=vm.runInContext('LoadRuntimeCredentials()',context,{timeout:1000});
process.stdout.write(JSON.stringify({frame_complete:result!==false,reason:context.reason,
  payload:result===false ? null : Buffer.from(result.payload).toString('ascii'),
  elapsed:now,opened,closed,readCalls}));
"""


def _read(chunks: list[tuple[int, str]], **options: object) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js required for actual-body cross-language checks")
    completed = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps({"source": str(EA), "chunks": [{"at": t, "text": s} for t, s in chunks], **options}),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize(
    "chunks",
    [
        [(0, "00000003abc")],
        [(250, "00000003abc")],
        [(0, "000"), (30, "00003"), (100, "a"), (250, "bc")],
    ],
)
def test_reads_complete_frame_on_same_connection(chunks: list[tuple[int, str]]) -> None:
    result = _read(chunks)
    assert result["frame_complete"] is True
    assert result["payload"] == "abc"
    assert result["opened"] == result["closed"] == 1


def test_empty_pipe_wait_is_bounded() -> None:
    result = _read([])
    assert result["frame_complete"] is False
    assert result["elapsed"] == 5000
    assert result["opened"] == result["closed"] == 1


def test_header_and_payload_share_one_deadline() -> None:
    result = _read([(4900, "00000003a"), (5100, "bc")])
    assert result["frame_complete"] is False
    assert result["reason"] == "CREDENTIAL_PAYLOAD_TRUNCATED"
    assert result["elapsed"] == 5000


def test_stop_cancels_wait_and_closes_handle() -> None:
    result = _read([], stopAt=30)
    assert result["frame_complete"] is False
    assert result["elapsed"] == 30
    assert result["closed"] == 1


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ("abcdefgh", "CREDENTIAL_SCHEMA_INVALID"),
        ("00004097", "CREDENTIAL_PAYLOAD_OVERSIZE"),
        ("00000000", "CREDENTIAL_PAYLOAD_OVERSIZE"),
        ("000", "CREDENTIAL_SCHEMA_INVALID"),
        ("00000003ab", "CREDENTIAL_PAYLOAD_TRUNCATED"),
        ("00000003abcX", "CREDENTIAL_TRAILING_BYTES"),
    ],
)
def test_invalid_frames_stay_rejected(data: str, reason: str) -> None:
    result = _read([(0, data)])
    assert result["frame_complete"] is False
    assert result["reason"] == reason
    assert result["closed"] == 1


def test_permanent_read_error_does_not_spin() -> None:
    result = _read([], readError=5001)
    assert result["frame_complete"] is False
    assert result["elapsed"] == 0
    assert result["closed"] == 1


def test_open_failure_does_not_reconnect() -> None:
    result = _read([], openFails=True)
    assert result["frame_complete"] is False
    assert result["reason"] == "CREDENTIAL_PIPE_UNAVAILABLE"
    assert result["opened"] == 1
    assert result["closed"] == 0


@pytest.mark.parametrize("durations", [[5000], [0, 5000]])
def test_read_returning_at_deadline_cannot_complete_frame(durations: list[int]) -> None:
    result = _read([(0, "00000003abc")], readDurations=durations)
    assert result["frame_complete"] is False
    assert result["closed"] == 1


@pytest.mark.parametrize("durations", [[50], [0, 50]])
def test_stop_during_successful_read_cannot_complete_frame(durations: list[int]) -> None:
    result = _read([(0, "00000003abc")], readDurations=durations, stopAt=30)
    assert result["frame_complete"] is False
    assert result["closed"] == 1


def test_trailing_read_error_is_not_eof() -> None:
    result = _read([(0, "00000003abc")], errorAtRead=3)
    assert result["frame_complete"] is False
    assert result["closed"] == 1


@pytest.mark.parametrize(
    "options",
    [
        {"readDurations": [0, 0, 5000]},
        {"readDurations": [0, 0, 50], "stopAt": 30},
    ],
)
def test_trailing_read_cannot_accept_after_deadline_or_stop(options: dict) -> None:
    result = _read([(0, "00000003abc")], **options)
    assert result["frame_complete"] is False
    assert result["closed"] == 1


def test_maximum_payload_is_accepted_at_size_boundary() -> None:
    result = _read([(0, "00004096"), (0, "a" * 4096)])
    assert result["frame_complete"] is True
    assert len(result["payload"]) == 4096
    assert result["opened"] == result["closed"] == 1


@pytest.mark.xfail(
    strict=True,
    reason="Open native EOF/closure gap: zero bytes can precede delayed trailing data; blocks acceptance",
)
def test_delayed_trailing_byte_must_not_complete_frame() -> None:
    result = _read([(0, "00000003abc"), (100, "X")])
    assert result["frame_complete"] is False
