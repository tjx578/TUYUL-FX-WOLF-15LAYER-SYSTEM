# G6 source candidate manifest: separate evidence for `1eb88680`

This folder is **evidence about** the frozen source candidate. It is **not part of** that candidate.

- Frozen source candidate: `1eb88680bf05ee1456ebb08acb8214e392ca2ac3`.
- Branch: `wolf15-v31-demo-candidate`, draft PR #518.
- Frozen by the owner on 2026-09-28.

Nothing here changes the candidate branch. Merging this folder would not change the candidate SHA either.

| File | Role |
|---|---|
| `CANDIDATE_MANIFEST_1eb88680.json` | The manifest (schema `wolf15.v31-g6.source-candidate-manifest.v2`): sha256 `0f9f0596254eb9ec34678955b599eeecf4763fb91572c438951a70ef576be8fa`, 7632 bytes |
| `candidate_manifest.py` | Deterministic generator. It reads only git objects of the candidate commit, refuses any other commit, checks every authority pin, and checks that every lane head is an ancestor of the candidate |
| `.gitattributes` | `* -text`, so the manifest bytes are identical on every checkout |

## What the manifest binds
- **Candidate:** `candidate_git_sha` and `candidate_tree_digest` (`3c53ca9aeb5a7a75ae05a20bc401a6a358be2ea7`).
- **Authority hashes:** `SSOT_sha256` `6daea387…`, `A1_sha256` `1fed7f7b…`, `A2_sha256` `9cf9e531…`, `A3_sha256` `538b3b6f…`, `A4_sha256` `357a55b0…`, and `R9_freeze_sha256` `2a5826a3…`.
- **R9 frozen pins:** schema bytes `10732eeb…` and normative span `c9663fa7…`.
- **Lane heads:** main `2ea21786`, StructuralGeometry #513 `bd6cae9a`, G4 #516 `4b103905`, A4 record #511 `68b74f21`, R9 #517 `26e038eb`, Lane E #514 `267c0724`, Lane F #515 `8ab7b4ae`.
- **Policies:** Lane E policy 1.5.0 (the D1 exempt fields). G4 `minimum_net_rr` 1.5; the G4 policy instance is supplied at evaluation.
- **Runtime binding:**
  - `EA_EX5_SHA256`, `EA_PRESET_SHA256` and `DEMO_ACCOUNT_BINDING` are `NOT_MEASURED`.
  - `RUNTIME_CANDIDATE_BINDING` is `NOT_FROZEN`.
- **Gates and effects:**
  - `R9_PASS` and `NATURAL_30_PAIR_SHADOW` are `NOT_EXECUTED`.
  - `G6_READY` and `G6_READY_FOR_DEMO` are `false`.
  - `BROKER_EFFECT` and `COMMAND_ENQUEUE_ARM_ORDER` are 0.

## Self-verification (PowerShell 5.1, run from any clone that has fetched `origin`)

```powershell
git fetch origin wolf15-v31-demo-candidate
git --no-pager rev-parse origin/wolf15-v31-demo-candidate
python docs/evidence/g6-source-candidate-1eb88680/candidate_manifest.py . 1eb88680bf05ee1456ebb08acb8214e392ca2ac3 $env:TEMP\g6_manifest_check.json
(Get-FileHash $env:TEMP\g6_manifest_check.json -Algorithm SHA256).Hash
(Get-FileHash docs/evidence/g6-source-candidate-1eb88680/CANDIDATE_MANIFEST_1eb88680.json -Algorithm SHA256).Hash
```

What to expect:
- The first hash printed must be `1EB88680BF05EE1456EBB08ACB8214E392CA2AC3`, and both `Get-FileHash` values must be `0F9F0596254EB9EC34678955B599EEECF4763FB91572C438951A70EF576BE8FA`.
- If the candidate branch has moved, the `rev-parse` output shows it; the generator still pins the commit explicitly.

A matching hash is evidence, not a runtime qualification. The runtime binding and G6 remain open until the operator measures the EX5, preset and DEMO account, R9 passes, and the natural 30-pair SHADOW passes.
