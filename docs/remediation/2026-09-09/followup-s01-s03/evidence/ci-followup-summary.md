# Exact API dependency and CI follow-up

Verdict: **PASS_LOCAL_BOUNDED_SUBSETS; REMOTE_CI_NOT_EXECUTED; FULL_SUITE_NOT_EXECUTED**.

The tested source is PR #423 branch `codex/master-remediation-20260909`, commit `261a3b476055accc3d0ea45ebc80a910e0e80f6b`. The repository source and test-file digests stayed unchanged during both recorded test runs. No source/dependency/CI file was edited by this follow-up, and no commit was made.

## Exact dependency evidence

- A new Windows Python 3.11.9 venv was built under the authorized C staging directory. All downloads/install output and test temp/XML files are there.
- Installed the full, unmodified `requirements.txt` through isolated pip against public PyPI. Install exit 0; `pip check` exit 0 with `No broken requirements found`.
- Requirements SHA256: `1f80669466b282c4e391effe904e5747e2150e87d4623324d10d391531923afb`.
- 43 direct requirement entries evaluated: 42 applicable entries satisfied; the existing Windows marker excludes uvloop. This does not verify Linux dependency closure or uvloop runtime.
- Important exact pins: Pydantic 2.9.2, pydantic-settings 2.5.2, pydantic-core 2.23.4, pytest 8.3.2, pytest-asyncio 0.24.0, pytest-cov 6.0.0, pandas 2.2.2, httpx 0.27.2. Allowed ranges resolved to FastAPI 0.141.1, Starlette 0.52.1, NumPy 2.4.6, Redis 8.1.0 and the other versions in `api-exact-version-closure.json`.
- The isolated API environment has no mcp, MetaTrader5 or psutil package. The separate required native MCP CI job remains unchanged. No API pin was relaxed to accommodate MCP2.
- Full resolver succeeded; no dependency change is justified by this evidence alone.

## Executed local subsets

| Subset | Collected / XML actual | Failures | Errors | Skipped | Source stable |
|---|---:|---:|---:|---:|---|
| API boot/readiness, API-only entrypoints, required CI gates, release source gate | 93 / 93 | 0 | 0 | 0 | yes |
| Existing pair admission and raw admission blocks | 33 / 33 | 0 | 0 | 0 | yes |

The first subset ran `tests/test_api_boot_readiness.py`, `tests/test_api_only_entrypoints.py`, `tests/test_ci_required_gates.py` and `tests/test_railway_release_source_gate.py`. The second ran `tests/test_strategy_5scr_pair_admission.py` and `tests/test_strategy_5scr_raw_admission_blocks.py`.

Exact collection and execution argument arrays, individual expected test IDs, source snapshots, timings and XML counts are in the respective `*-receipt.json` files. Commands used `-p no:cacheprovider`, `--timeout=60`, C-only `--basetemp` and `--junitxml`, and `PYTHONDONTWRITEBYTECODE=1`. Normal conftests were loaded. The subprocess environment omitted inherited provider credentials, disabled dotenv/risk execution, and used unavailable localhost fixture DB/Redis URLs. No production service, database or broker was accessed.

Warnings are recorded separately: Starlette's deprecated BlockingPortal alias, and pytest-asyncio's unset future fixture-loop-scope default. Neither caused a failure in these runs. The source admission subset validates existing behavior only; it does not close newly developed S03 activity/advisory behavior, persistence, or production acceptance.

## Remote CI and source drift

PR #423 was freshly verified at head `261a3b476055accc3d0ea45ebc80a910e0e80f6b`, initially based on `773150952311db3dbf5188f36536b7837d8ec296`. CI runs 34271414731 and 34271388045 report failure. The latest run has seven jobs; every job has runner_id 0 and no steps. Thus executable remote checks are NOT_EXECUTED. No billing action, workflow rerun, provider action or gate relaxation occurred.

During the follow-up, remote main independently advanced to `2b060f8e55beedd21340cda37bfb0a70c238386e` through PR #424. Commit metadata reports four added files: `.codex/SETTINGS-LOCAL.md`, `.codex/config.toml`, `.codex/rules/settings-local.rules` and `settings.local.json`, with no application-file change. These settings were not loaded or executed by this audit. PR baseRefOid still returned the older base, so fresh main ref must govern subsequent merge/release binding. The branch tests do not establish a tested combined tree on the new main.

## Artifact handling

Copy only `ci-evidence/` receipts/logs/XML and the two bounded runner/summary scripts if desired. Do not commit or copy the venv, downloaded packages or temporary pytest directories. Before the parent clarified the C-only write boundary, an initial D-local venv and three D evidence JSONs were created; they were left untouched thereafter, and the JSONs were copied to C staging. All installation and actual test receipts reported here are from the C-local environment.

No full repository CI, production migration, Linux runner proof, new S03 implementation validation, natural DEMO, broker fill, release or main merge is claimed.
