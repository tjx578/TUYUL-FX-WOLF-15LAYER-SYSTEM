# Verdict Recovery Sign-Off Pack

This runbook turns the remaining Section 7 verification gates from `analysis/STRATEGIC_BLUEPRINT_2026-04-22.md` into concrete artifacts and executable evidence paths.

## Current Status

- Clarity: recorded in `docs/CHANGELOG_VERDICT_RECOVERY.md`.
- Slice verification: recorded in `journal/verification/2026-04-22-post-p6-execution-observability.json`.
- Review gate: pending evidence collection in `journal/verification/2026-04-22-review-gate.json`.
- Security gate: pending evidence collection in `journal/verification/2026-04-22-security-gate.json`.
- Performance gate: pending evidence collection in `journal/verification/2026-04-22-performance-gate.json`.

## Review Gate

- Goal: satisfy the blueprint requirement for independent review before production sign-off.
- Required roles: code reviewer specialist, security reviewer, performance reviewer.
- Focus scope:
  - `execution/broker_executor.py`
  - `execution/ea_manager.py`
  - `execution/execution_router.py`
  - `api/allocation_router.py`
  - `tests/test_broker_executor.py`
  - `tests/test_execution_router.py`
  - `tests/test_write_governance_policy.py`
- Evidence location: `journal/verification/2026-04-22-review-gate.json`

## Security Gate

- Goal: prove the post-P6 execution evaluation slice keeps secrets, account state, and authority boundaries intact.
- Primary evidence sources:
  - `.github/workflows/wolf-security-scan.yml`
  - `tests/contract/test_blueprint_v2_contracts.py`
  - `tests/test_broker_executor.py`
  - `tests/test_execution_router.py`
- Minimum commands to attach:
  - `python -m pytest tests/contract/test_blueprint_v2_contracts.py -q`
  - `python -m pytest tests/test_broker_executor.py tests/test_execution_router.py -q`
  - CI or local results equivalent to `pip-audit --desc --strict --ignore-vuln CVE-2026-4539`
  - CI or local results equivalent to TruffleHog filesystem scan using `.github/trufflehog-exclude.txt`
- Evidence location: `journal/verification/2026-04-22-security-gate.json`

## Performance Gate

- Goal: prove the verdict recovery slice does not regress latency-sensitive paths beyond blueprint budgets.
- Primary evidence sources:
  - `.github/workflows/perf-guard.yml`
  - `tests/integration/test_9gate_concurrent.py`
  - `tests/integration/test_feed_to_verdict_latency.py`
  - `tests/load/k6_ws_test.js`
- Minimum commands to attach:
  - `python -m pytest tests/integration/test_9gate_concurrent.py -q`
  - `python -m pytest tests/integration/test_feed_to_verdict_latency.py -q`
  - CI or local results equivalent to the import-time budget and slow-test enforcement in `.github/workflows/perf-guard.yml`
- Evidence location: `journal/verification/2026-04-22-performance-gate.json`

## Sign-Off Rule

- Production sign-off remains blocked until all three pending gate artifacts move from `pending_evidence` to `ready_for_signoff` or `passed` with attached evidence.
- Execution must remain fail-closed while any of the above artifacts are still pending.
