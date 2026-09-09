# Isolated native MCP fixture dependency validation

**7 tests passed, zero failed/skipped, 70.42 seconds.** Seven warnings concern the repository `event_loop_policy` fixture deprecated by pytest-asyncio1.4.0. The test suite exercises FakeMT5 objects and in-process MCP registry listing, not an actual terminal or broker.

Host Python did not have `mcp`. Exact repository pin `mcp==2.0.0` was available from official PyPI and downloaded successfully: wheel `mcp-2.0.0-py3-none-any.whl`,349,980 bytes, SHA256 `1cb4c75d2d2c7b8c1d756355e5d82a39f2822cc7f13e22a2051d7ca3592349d6`.

Installed only in `D:/WOLF15-work/master-remediation-20260909/mcp-test-env`, without global or source edits. Selected package versions:

| Package | Version |
|---|---|
| Python | 3.11.9 |
| mcp | 2.0.0 |
| mcp-types | 2.0.0 |
| psutil | 7.2.2 |
| pydantic | 2.13.5 |
| pytest | 8.4.2 |
| pytest-asyncio | 1.4.0 |
| pytest-timeout | 2.4.0 |

`pip check` reports no broken requirements in this isolated environment. Full dependency freeze is `mcp-dependency-validation-freeze.txt`.

Exact mcp wheel metadata requires Python>=3.10 and Pydantic>=2.12.0. Root `requirements.txt` pins Pydantic2.9.2. These constraints cannot be satisfied in one environment. This result supports a separate required fixture-only MCP CI job; it does not demonstrate a compatible combined API/native MCP dependency set. Do not loosen pins silently or present this separate-environment PASS as full-service acceptance.

Executed only `tests/test_native_mt5_readonly_mcp.py` through external `mcp_dependency_fixture_runner.py`. All bridge fixtures inject `FakeMT5`; the external runner additionally forbids native `MetaTrader5` imports and clears MT5/account-binding environment fields without disclosing their contents. MetaTrader5 is not installed in the venv. No actual terminal initialization, credentials, account-binding packet, MCP server launch or broker operation occurred. Current test source/bridge hashes, exact commit and native-import counter are recorded in `mcp-dependency-validation.json`; JUnit in `mcp-dependency-validation.xml`.

Validated capabilities are limited to five-tool registry metadata, fake read-only method usage, free-text redaction, empty/error distinction, history bounds, pinned-path checks, absent-HMAC rejection and consistent fixture HMAC identity. Actual account/reader/terminal verification remains NOT_MEASURED. C03 remains PARTIAL beyond this local dependency/fixture prerequisite.
