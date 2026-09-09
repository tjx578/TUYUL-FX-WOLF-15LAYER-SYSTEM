# Candidate security remediation

Scope: the integrated P1 candidate, including the pursuit/K05/Transaction A files.
This is source/dependency evidence, not production deployment or runtime acceptance.

## Dependency decisions

The previous pip-audit log contains 11 rows but eight distinct PYSEC identifiers.
Rows are preserved in the prior artifact; duplicate advisories are not additional
vulnerabilities. The following floors remove the reported affected versions:

| Package | Previous version | Selected requirement | Advisory identifiers |
| --- | --- | --- | --- |
| pytest | 8.3.2 | 9.0.3 | PYSEC-2026-1845 |
| python-dotenv | 1.0.1 | 1.2.2 | PYSEC-2026-2270 |
| setuptools | 79.0.1 | >=83.0.0 | PYSEC-2026-3447 (two rows) |
| Starlette | 0.52.1 | >=1.3.1,<2 | PYSEC-2026-161 (two rows), 248 (two rows), 249, 2281, 2280 |

The former Starlette `<1` cap prevented installation of the security fixes.
FastAPI's floor is now 0.141.1, whose published metadata accepts Starlette >=0.46
without that upper cap and Pydantic >=2.9. pytest-asyncio 0.24 requires pytest <9;
1.3.0 accepts pytest >=8.2,<10 and is selected to admit the patched pytest.
The isolated build-system setuptools floor matches requirements.txt.
No application authorization, routing, broker, or strategy code changes accompany
these dependency changes. The framework and test plugin transitions require the
candidate suite and owner-login compatibility tests, not merely resolver success.

Authoritative references checked on 2026-09-09:

- [pytest 9.0.3 release](https://github.com/pytest-dev/pytest/releases/tag/9.0.3)
- [python-dotenv advisory](https://github.com/advisories/GHSA-mf9w-mj56-hr94)
- [setuptools 83.0.0 release](https://github.com/pypa/setuptools/releases/tag/v83.0.0)
- [Starlette 1.3.1 release](https://github.com/Kludex/starlette/releases/tag/1.3.1)
- [FastAPI 0.141.1 metadata](https://pypi.org/pypi/fastapi/0.141.1/json)
- [pytest-asyncio 1.3.0 metadata](https://pypi.org/pypi/pytest-asyncio/1.3.0/json)

## Secret candidate triage

The prior 15 occurrences were reproduced by exact-value comparison locally.
Eighteen further occurrences in pursuit receipts are copies of pytest rejected
database-target parameter IDs. All 33 observations are accounted for individually
in `secret-triage.json`; 31 distinct path/detector/value tuples are recorded in
`secret-reviewed-fingerprints.json` (two redaction occurrences share a value/path).
No value was used to authenticate. No raw scanner output is committed or printed.

The reviewed values are public Railway project/environment UUIDs (including
matching archived ZIP members), reserved-domain URI negative fixtures, and
synthetic PostgreSQL redaction/rejected-target fixtures. The latter are locally
matched to the original test literals and scanner normalization, not inferred
safe merely from a test filename or host. Receipt/XML copies are collection node
IDs rather than runtime connection configuration.

The filter does not exclude files or detectors. It accepts only an unverified
finding with the exact detector, path, value SHA256, and LF-normalized whole-file
SHA256 already reviewed. Changed content, a new value, a different location/file,
a verified result, malformed output, or any scanner error remains a failure.
Hashes are of reviewed benign literals only; they are not leaked credential hashes.

## Verification boundaries

The downloaded TruffleHog 3.97.4 Windows archive matched the publisher checksum:
`6ce9a957ac62bfb19463048333d9e8481327dbbf5bdc0c43f5ab5327b9631fb9`.
The local process ended with exit 1 without a completion receipt. Its findings
can support triage but cannot establish complete scan coverage. Linux CI must run
the complete scanner and then the filter; exit 1 is deliberately not accepted.

The existing exclusion file was not broadened. Therefore a passing CI scan remains
bounded by its pre-existing exclusions; it is not proof about all Git history or
every production credential. Provider verification stays NOT_EXECUTED by design.

The clean dependency environment and remote candidate test receipts are tracked
by the parent integration report. Full security PASS must come from the final
candidate's complete audit/scan jobs, not these static classifications alone.
