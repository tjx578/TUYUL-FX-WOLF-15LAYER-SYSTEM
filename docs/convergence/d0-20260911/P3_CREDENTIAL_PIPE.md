# P3 — Runtime credential isolation (PORT_WITH_REPAIR)

**Branch:** `feat/d0-runtime-credential-pipe`, based on P2 `fa794a3e`
**Verdict:** ported, repaired, and **functionally proven** — 16/16 live gates
**Decision:** `CREDENTIAL_PIPE_ARCHITECTURE = KEEP` · `#446 IMPLEMENTATION AS-IS = DO NOT CHERRY-PICK`

---

## 1. What was kept from #446

The architecture is sound and is preserved unchanged:

```
DPAPI-encrypted vault (CurrentUser)
        v
one-shot Windows helper
        v
same-user ACL named pipe
        v
bounded 8-byte ASCII length frame
        v
canonical JSON, exact ordered fields
        v
EA runtime memory
        v
executor token + verification material
```

No network surface, no plaintext credential file, no console secret output, no
`#import` / DLL requirement on the MQL5 side. Payload bounded to 4096 bytes, one
server instance, one serve.

The MQL5 loader in #446 was already strong: digits-only header, exact-length
payload read, trailing-byte check, and a **canonical round-trip** — the envelope
is re-serialised from the parsed fields and compared byte-for-byte, which rejects
missing, reordered, duplicated and unknown fields in one step. That design was
ported, not rewritten.

## 2. What was repaired

### R-1 — hardcoded Windows username removed

#446 shipped an `EndsWith` check against a literal account name in canonical
source, and `"server_identity": "CURRENT_WINDOWS_USER_INTEL"` in the contract.
That adds no real boundary — DPAPI `CurrentUser` plus a pipe ACL restricted to
the running SID already is the boundary — while pinning the artifact to one
workstation.

Replaced by `ResolveCurrentUserSid()`: the SID is resolved at runtime and used
for the pipe ACL. An optional `--expected-user-sid` argument gives an explicit,
non-secret extra binding for operators who want one. The contract now reads
`CURRENT_WINDOWS_USER` / `RUNTIME_SID`. No workstation account literal remains
anywhere in canonical source or contract.

### R-2 — input named for what it actually is

`InpCredentialFile` → **`InpCredentialPipePath`**. The value is a Windows local
named-pipe endpoint, not a file. The honest name also stops a future operator
assuming credentials may be parked on disk.

### R-3 — exact lowercase-hex contract for both secrets

The backend derives the token as an HMAC-SHA256 `hexdigest()`, so canonical form
is exactly 64 lowercase hex characters. Length alone would accept uppercase or
non-hex input.

```
executor_token         length 64, alphabet [0-9a-f], uppercase rejected
verification_material  "hex:" + 64 lowercase hex -> 32 bytes
verification_key_id    IsSafeWireIdentifier
```

`IsLowerHexExact()` has no uppercase branch: uppercase is rejected, never
normalised. The EA does **not** attempt to derive or cryptographically verify the
bearer token — it holds no bridge auth secret, and the server remains the
authentication authority. The EA only proves the envelope is structurally
canonical before use.

### R-4 — two overclaims corrected in the contract itself

```
account_reference_sha256_authority = LOCAL_CREDENTIAL_BINDING_ONLY
account_identity_authority         = CHANNEL_B_W15AB_V1
secret_zeroization                 = BEST_EFFORT_BYTE_BUFFERS_ONLY
```

`account_reference_sha256` is an unkeyed digest of a low-entropy reference. It
binds the envelope locally and **must never** be presented as broker/database
account identity. **Blocker B-B16 stays open; P4 is still required.**

On zeroization the honest status is:

| Claim | Status |
|---|---|
| logical credential lifetime bounded | YES |
| best-effort byte-buffer clearing | YES |
| guaranteed process-memory zeroize | **NO** |

.NET `string` and MQL5 `string` are immutable; assigning an empty string does not
scrub the old allocation. `ClearRuntimeCredentials()` bounds the logical lifetime
and runs on every `OnInit` failure path and on `OnDeinit`, which is what is
actually true.

## 3. Toolchain finding — no .NET SDK needed

This host has **no .NET SDK** (`dotnet --list-sdks` empty; no `csc`/`msbuild` on
PATH; only the .NET 8 runtime). The helper nevertheless compiles with the in-box
.NET Framework 4.8 compiler under
`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, because it targets
`System.Web.Extensions`, `System.Security` and `System.IO.Pipes`.

That is a property worth keeping: an operator needs **no SDK install** to build
the credential broker.

```
csc -nologo -target:exe -out:Wolf15CredentialBroker.exe ^
    -r:System.Web.Extensions.dll -r:System.Security.dll ^
    Wolf15CredentialBroker.cs
```

## 4. Functional acceptance — the part nobody had done

#446's test was source grep only. It never showed the helper compiled, DPAPI
decrypted, a pipe was created, or a frame was framed correctly. This run does.

Bound to helper source `tools/windows/wolf15_credential_broker/Wolf15CredentialBroker.cs`.

The binding is recorded as the **git blob hash**, which is content-addressed and
therefore independent of checkout line endings:

```
git rev-parse HEAD:tools/windows/wolf15_credential_broker/Wolf15CredentialBroker.cs
9738d843cd1c7ec39c890a2c0a02d22d54b05a72
```

A plain SHA-256 of the working-tree file is **not** reproducible here: this repository
normalises to LF in the object store and checks out CRLF on Windows, so the same blob
yields different digests in different worktrees (observed: 14,239 bytes with 375 LF
versus 14,614 bytes with 375 CRLF, a 375-byte difference that is exactly the added CR
octets). Over LF-normalised bytes the digest is stable and is:

```
de66c8bd1ce92bc087458952000b871801340b066f9c24a5c6fa62e643ebd42c
```

reproducible with:

```
python -c "import hashlib,io,sys; print(hashlib.sha256(io.open(sys.argv[1],chr(114)+chr(98)).read().replace(bytes([13,10]),bytes([10]))).hexdigest())" tools/windows/wolf15_credential_broker/Wolf15CredentialBroker.cs
```

Quote the blob hash when binding evidence to this helper; quote the SHA-256 only
together with the normalisation it assumes.
| Gate | Check | Result | Evidence |
|---|---|---|---|
| C16 | helper compiles with in-box compiler | **PASS** | csc exit 0, no SDK |
| C17 | DPAPI Unprotect + vault digest + schema accepted | **PASS** | helper exit 0 |
| C18a | 8-byte ASCII header equals payload byte length | **PASS** | header `00000406` |
| C18b | payload is the exact canonical envelope | **PASS** | 406 bytes, byte-equal |
| C18c | no trailing bytes after payload | **PASS** | trailing read 0 |
| C18d | payload within the 1..4096 bound | **PASS** | 406 |
| C02C03 | envelope carries token + verification material | **PASS** | both present |
| C13 | serves once then exits, second connect refused | **PASS** | second connect failed |
| C12 | pipe ACL grants only the current user SID | **PASS** | exactly one rule, matching SID |
| C19 | foreign `--expected-user-sid` fails closed | **PASS** | exit 2 `WRONG_WINDOWS_USER` |
| C19b | matching `--expected-user-sid` still serves | **PASS** | exit 0 |
| C15a | vault digest mismatch fails closed | **PASS** | exit 2 `CREDENTIAL_VAULT_DIGEST_MISMATCH` |
| C15b | missing vault fails closed | **PASS** | exit 2 `CREDENTIAL_VAULT_UNAVAILABLE` |
| C08h | unknown vault field fails closed | **PASS** | exit 2 `CREDENTIAL_SCHEMA_INVALID` |
| C09 | executor binding mismatch fails closed | **PASS** | exit 2 `EXECUTOR_BINDING_MISMATCH` |
| C14a | pipe name outside reserved prefix fails closed | **PASS** | exit 2 `ARGUMENT_CONTRACT_INVALID` |
| C20 | absent pipe fails closed for the consumer | **PASS** | connect threw |

```
TOTAL=16 FAILED=0
```

C12 is the strongest single result: the ACL read back from the connected client
end contained **exactly one** access rule, and it was the running account's SID.

### Why the harness is reproduced here instead of stored as a .ps1

On this build host an **unidentified process** takes an exclusive handle on this
specific script content, and the file became unreadable even to `git add`:

```
error: open("tools/windows/wolf15_credential_broker/acceptance.ps1"): Permission denied
error: unable to index file
```

What is actually established: a trivial `.ps1` written to the same directory stayed
readable; byte-identical content ran fine from a scratch directory on `C:`; and the
file ACLs are normal, so this is a sharing violation rather than a permissions
problem. The trigger therefore correlates with content **and** location.

What is **not** established: which process holds the handle. Attributing it to
antivirus heuristics is a plausible hypothesis — the script combines DPAPI, named
pipes, process spawning and runtime C# compilation — but no host log or handle
diagnosis was captured to support it, so it is recorded as a hypothesis, not a finding.

Security settings were **not** modified to work around it. The harness is reproduced
verbatim below; save it next to `Wolf15CredentialBroker.cs` and run:

```
powershell -NoProfile -ExecutionPolicy Bypass -File acceptance.ps1
```

**Open item for the owner.** Closing this needs a handle diagnosis on the host to
identify the holder before any mitigation is chosen. An antivirus exclusion is **not**
recommended as the next step: that would be a security-settings change made on an
unverified cause.

Evidence status while that stays open:

```
WINDOWS_FUNCTIONAL_RESULT       = PASS_REPORTED
HARNESS_SOURCE_PRESERVED        = REPORTED
REPRODUCIBLE_WINDOWS_ACCEPTANCE = OPEN
```

`PASS_REPORTED` means the 16 gates were executed and observed on this host and
toolchain. It does not mean they have been independently reproduced from reviewed
source in an approved test environment.
## 5. Source-contract coverage

`tests/test_mt5_dpapi_pipe_credential_loader.py` — 15 tests covering C01 and
C04–C11, plus the repairs above and a guard that P2's monotonic scheduler
survived P3.

## 6. Acceptance summary

| Gate | Requirement | Result |
|---|---|---|
| C01 | direct secret EA inputs removed | PASS |
| C02 | executor token loaded only at runtime | PASS |
| C03 | verification material loaded only at runtime | PASS |
| C04–C07 | malformed / truncated / oversize / trailing rejected | PASS (source contract) |
| C08 | unknown / extra JSON fields rejected | PASS (canonical round-trip + live C08h) |
| C09–C11 | executor / account-reference / key-id mismatch rejected | PASS |
| C12 | pipe ACL = current Windows user only | **PASS (live)** |
| C13 | helper is one-shot | **PASS (live)** |
| C14 | helper network calls = 0 | PASS |
| C15 | plaintext credential file = 0 | PASS |
| C16 | helper compiles on target Windows toolchain | **PASS (live)** |
| C17 | DPAPI round-trip functional | **PASS (live)** |
| C18 | named-pipe frame functional | **PASS (live)** |
| C19 | wrong Windows user/SID fails closed | **PASS (live)** |
| C20 | missing pipe fails closed | **PASS (live)** |
| C21 | Demo OrderCheck count unchanged | PASS — 1 to 1 |
| C22 | Demo OrderSend count unchanged | PASS — 1 to 1 |
| C23 | Shadow OrderSend count = 0 | PASS — 0 to 0 |
| C24 | P2 monotonic scheduler tests remain PASS | PASS |
| C25 | baseline D0 suite remains PASS | recorded in the commit message |

MetaEditor integration compile remains **P6**, unchanged.

### What these numbers do and do not prove

The 15 source-contract tests, the 16 live helper gates and the D0 focused suite test
three different boundaries and **must not be added into one end-to-end figure**:

| Evidence | Proves | Does not prove |
|---|---|---|
| 15 source-contract tests | the MQL5 / C# / JSON contract shape | any MQL5 execution |
| 16 live helper gates | the C# broker compiles, decrypts, frames, ACLs, and fails closed | that a native EA read the frame |
| D0 focused suite | Python-side behaviour at this SHA | anything about MQ5 or EX5 |

Specifically still unproven: **a native MQL5 EA reading the full frame from the pipe,
handling failure, and not hanging.** The ACL read-back is strong evidence about access
configuration on that run, which is a different claim from native consumption. That,
and Channel B `w15ab:v1` / B-B16, remain outside P3.

## 7. Not touched

`direct_broker_reconciliation_repository.py`, `mt5_demo_canary_authority_packet.py`,
strategy / SSOT, risk, database migrations, Channel B schema, Railway,
`OrderSend` / `OrderCheck` semantics, command schema, and the P2 timer semantics.

## Appendix — acceptance harness (verbatim)

```powershell
# P3 functional acceptance for the ported Wolf15 credential broker.
# Proves: DPAPI round-trip, named-pipe framing + ACL, one-shot serving, and
# fail-closed rejections. Read-only with respect to the repository.
#
# Fixture values are space-free: PowerShell 5.1 Start-Process joins ArgumentList
# naively, so a space would split one argument into two and break the helper's
# 9/10 argument contract. That is a harness limitation, not a contract claim.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

$build = $PSScriptRoot + '\p3build'
$exe   = $build + '\Wolf15CredentialBroker.exe'

$results = New-Object System.Collections.ArrayList
function Gate($id, $name, $ok, $detail) {
    $null = $results.Add([pscustomobject]@{
        Gate = $id; Check = $name
        Result = $(if ($ok) { 'PASS' } else { 'FAIL' }); Detail = $detail
    })
}

$executorId   = 'wolf15-d0-executor-0000000000000001'
$accountRef   = 'demo-account-reference-0001'
$brokerServer = 'XMGlobal-MT5-10'
$keyId        = 'w15key-d0-0001'
$token        = ('a' * 32) + ('b' * 32)
$verifyKey    = 'hex:' + ('c' * 64)

$sha = [System.Security.Cryptography.SHA256]::Create()
function Sha256Hex([byte[]]$bytes) { -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) }
$accountRefSha = Sha256Hex([System.Text.Encoding]::UTF8.GetBytes($accountRef))

function New-Vault([string]$path, [string]$json) {
    $plain  = [System.Text.Encoding]::UTF8.GetBytes($json)
    $cipher = [System.Security.Cryptography.ProtectedData]::Protect($plain, $null, 'CurrentUser')
    [System.IO.File]::WriteAllBytes($path, $cipher)
    return Sha256Hex($cipher)
}

$goodJson = '{"schema":"wolf15.lean_d0.executor_credentials.v1","executor_id":"' + $executorId +
    '","account_id_reference":"' + $accountRef + '","broker_server":"' + $brokerServer +
    '","executor_token":"' + $token + '","verification_key_id":"' + $keyId +
    '","verification_key_type":"PER_EXECUTOR_HMAC","verification_key":"' + $verifyKey +
    '","issued_at_utc":"2026-09-11T00:00:00Z","expires_at_utc":null}'

$goodVault = $build + '\vault.bin'
$goodSha   = New-Vault $goodVault $goodJson

function Start-Broker([string]$vaultPath, [string]$digest, [string]$pipe, [int]$timeoutMs, [string[]]$extra) {
    $brokerArgs = @(
        '--vault', $vaultPath, '--vault-sha256', $digest, '--pipe-name', $pipe,
        '--executor-id', $executorId, '--account-reference', $accountRef,
        '--broker-server', $brokerServer, '--verification-key-id', $keyId,
        '--account-reference-sha256', $accountRefSha, '--timeout-ms', "$timeoutMs"
    ) + $extra
    # Start-Process -PassThru does not reliably surface ExitCode in Windows
    # PowerShell 5.1, so drive the process directly.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($brokerArgs | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardOutput = $true
    $psi.CreateNoWindow = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    return @{ Process = $p }
}

function Wait-Broker($run) {
    $stderr = $run.Process.StandardError.ReadToEnd()
    $run.Process.WaitForExit()
    $exit = $run.Process.ExitCode
    $run.Process.Dispose()
    $reason = ''
    if ($null -ne $stderr) { $reason = $stderr.Trim() }
    return @{ Exit = $exit; Reason = $reason }
}

function Read-Frame([string]$pipe, [int]$connectMs = 5000) {
    $client = New-Object System.IO.Pipes.NamedPipeClientStream('.', $pipe, [System.IO.Pipes.PipeDirection]::In)
    try {
        $client.Connect($connectMs)
        $header = New-Object byte[] 8
        $got = 0
        while ($got -lt 8) { $n = $client.Read($header, $got, 8 - $got); if ($n -le 0) { break }; $got += $n }
        if ($got -ne 8) { return @{ Ok = $false; Reason = "short header $got" } }
        $headerText = [System.Text.Encoding]::ASCII.GetString($header)
        if ($headerText -notmatch '^[0-9]{8}$') { return @{ Ok = $false; Reason = "bad header $headerText" } }
        $length = [int]$headerText
        $payload = New-Object byte[] $length
        $got = 0
        while ($got -lt $length) { $n = $client.Read($payload, $got, $length - $got); if ($n -le 0) { break }; $got += $n }
        if ($got -ne $length) { return @{ Ok = $false; Reason = "short payload $got/$length" } }
        $trailing = New-Object byte[] 1
        $extra = $client.Read($trailing, 0, 1)
        return @{ Ok = $true; Header = $headerText; Length = $length
                  Json = [System.Text.Encoding]::UTF8.GetString($payload); Trailing = $extra }
    } catch {
        return @{ Ok = $false; Reason = $_.Exception.Message }
    } finally { $client.Dispose() }
}

# --- C17 / C18: DPAPI round-trip and exact framing ---------------------------
$pipe1 = 'wolf15-lean-d0-accept-a'
$run1 = Start-Broker $goodVault $goodSha $pipe1 6000 @()
Start-Sleep -Milliseconds 600
$frame = Read-Frame $pipe1
$r1 = Wait-Broker $run1

Gate 'C17' 'DPAPI Unprotect + vault digest + schema accepted' ($frame.Ok -and $r1.Exit -eq 0) "exit=$($r1.Exit) $($frame.Reason)"

$expectedJson = '{"schema":"wolf15.runtime_credentials.v1","executor_id":"' + $executorId +
    '","account_reference_sha256":"' + $accountRefSha + '","verification_key_id":"' + $keyId +
    '","executor_token":"' + $token + '","verification_material":"' + $verifyKey + '"}'

Gate 'C18a' '8-byte ASCII decimal header equals payload byte length' `
    ($frame.Ok -and $frame.Length -eq [System.Text.Encoding]::UTF8.GetByteCount($frame.Json)) "header=$($frame.Header)"
Gate 'C18b' 'payload is the exact canonical envelope' ($frame.Ok -and $frame.Json -ceq $expectedJson) "len=$($frame.Length)"
Gate 'C18c' 'no trailing bytes after payload' ($frame.Ok -and $frame.Trailing -eq 0) "trailing=$($frame.Trailing)"
Gate 'C18d' 'payload within the 1..4096 byte bound' ($frame.Ok -and $frame.Length -ge 1 -and $frame.Length -le 4096) "len=$($frame.Length)"
Gate 'C02C03' 'envelope carries executor token and verification material' `
    ($frame.Ok -and $frame.Json.Contains($token) -and $frame.Json.Contains($verifyKey)) 'both credential fields present'

# --- C13: one-shot -----------------------------------------------------------
$second = $false
try { $c2 = New-Object System.IO.Pipes.NamedPipeClientStream('.', $pipe1, [System.IO.Pipes.PipeDirection]::In)
      $c2.Connect(800); $second = $true; $c2.Dispose() } catch { $second = $false }
Gate 'C13' 'serves once then exits; second connect refused' (-not $second) "second connect ok=$second"

# --- C12: ACL is the current user SID only -----------------------------------
$pipe2 = 'wolf15-lean-d0-accept-acl'
$run2 = Start-Broker $goodVault $goodSha $pipe2 6000 @()
Start-Sleep -Milliseconds 600
$aclOk = $false; $aclDetail = 'not observed'
try {
    # The ACL is readable from the connected client end of the pipe; File.Open on
    # a pipe path is not a valid probe.
    $probe = New-Object System.IO.Pipes.NamedPipeClientStream('.', $pipe2, [System.IO.Pipes.PipeDirection]::In)
    $probe.Connect(5000)
    $me = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
    $ids = @($probe.GetAccessControl().GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]) |
             ForEach-Object { $_.IdentityReference.Value })
    $aclOk = ($ids.Count -ge 1) -and (@($ids | Where-Object { $_ -ne $me }).Count -eq 0)
    $aclDetail = "rules=[$($ids -join ',')] me=$me"
    $probe.Dispose()
} catch { $aclDetail = "probe error: $($_.Exception.Message)" }
$null = Wait-Broker $run2
Gate 'C12' 'named-pipe ACL grants only the current user SID' $aclOk $aclDetail

# --- C19: explicit SID binding ------------------------------------------------
$foreignSid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
$run3 = Start-Broker $goodVault $goodSha 'wolf15-lean-d0-accept-sidbad' 800 @('--expected-user-sid', $foreignSid)
$r3 = Wait-Broker $run3
Gate 'C19' 'foreign --expected-user-sid fails closed' (($r3.Exit -eq 2) -and ($r3.Reason -match 'WRONG_WINDOWS_USER')) "exit=$($r3.Exit) reason=$($r3.Reason)"

$mySid = ([System.Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$pipe4 = 'wolf15-lean-d0-accept-sidok'
$run4 = Start-Broker $goodVault $goodSha $pipe4 6000 @('--expected-user-sid', $mySid)
Start-Sleep -Milliseconds 600
$frame4 = Read-Frame $pipe4
$r4 = Wait-Broker $run4
Gate 'C19b' 'matching --expected-user-sid still serves' ($frame4.Ok -and $r4.Exit -eq 0) "exit=$($r4.Exit)"

# --- fail-closed rejections ---------------------------------------------------
$run5 = Start-Broker $goodVault ('0' * 64) 'wolf15-lean-d0-accept-digest' 800 @()
$r5 = Wait-Broker $run5
Gate 'C15a' 'vault digest mismatch fails closed' (($r5.Exit -eq 2) -and ($r5.Reason -match 'CREDENTIAL_VAULT_DIGEST_MISMATCH')) "exit=$($r5.Exit) reason=$($r5.Reason)"

$badVault = $build + '\vault_extra_field.bin'
$badSha = New-Vault $badVault ($goodJson.Replace('"issued_at_utc"', '"issued_at_utc_typo"'))
$run6 = Start-Broker $badVault $badSha 'wolf15-lean-d0-accept-schema' 800 @()
$r6 = Wait-Broker $run6
Gate 'C08h' 'unknown vault field fails closed' (($r6.Exit -eq 2) -and ($r6.Reason -match 'CREDENTIAL_SCHEMA_INVALID')) "exit=$($r6.Exit) reason=$($r6.Reason)"

$mismVault = $build + '\vault_wrong_executor.bin'
$mismSha = New-Vault $mismVault ($goodJson.Replace($executorId, 'wolf15-d0-executor-0000000000009999'))
$run9 = Start-Broker $mismVault $mismSha 'wolf15-lean-d0-accept-exec' 800 @()
$r9 = Wait-Broker $run9
Gate 'C09' 'executor binding mismatch fails closed' (($r9.Exit -eq 2) -and ($r9.Reason -match 'EXECUTOR_BINDING_MISMATCH')) "exit=$($r9.Exit) reason=$($r9.Reason)"

$run7 = Start-Broker $goodVault $goodSha 'not-a-wolf15-pipe' 800 @()
$r7 = Wait-Broker $run7
Gate 'C14a' 'pipe name outside the reserved prefix fails closed' (($r7.Exit -eq 2) -and ($r7.Reason -match 'ARGUMENT_CONTRACT_INVALID')) "exit=$($r7.Exit) reason=$($r7.Reason)"

$run8 = Start-Broker ($build + '\does_not_exist.bin') $goodSha 'wolf15-lean-d0-accept-novault' 800 @()
$r8 = Wait-Broker $run8
Gate 'C15b' 'missing vault fails closed' (($r8.Exit -eq 2) -and ($r8.Reason -match 'CREDENTIAL_VAULT_UNAVAILABLE')) "exit=$($r8.Exit) reason=$($r8.Reason)"

# --- C20: consumer side sees no pipe when the helper never ran ---------------
$missing = $false
try { $c = New-Object System.IO.Pipes.NamedPipeClientStream('.', 'wolf15-lean-d0-never-served', [System.IO.Pipes.PipeDirection]::In)
      $c.Connect(800); $c.Dispose() } catch { $missing = $true }
Gate 'C20' 'absent pipe fails closed for the consumer' $missing 'connect threw as expected'

$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object { $_.Result -eq 'FAIL' }).Count
"TOTAL=$($results.Count) FAILED=$failed"
if ($failed -gt 0) { exit 1 } else { exit 0 }
```
