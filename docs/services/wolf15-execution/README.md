# wolf15-execution

**Role:** consolidated allocation and guarded execution worker service.

- Manifest: [`../../../railway-execution.toml`](../../../railway-execution.toml)
- Start script: [`../../../deploy/railway/start_trade_consolidated.sh`](../../../deploy/railway/start_trade_consolidated.sh)
- Runtime module: [`../../../services/trade/runner.py`](../../../services/trade/runner.py)

The process validates the execution plane before creating workers, starts the
allocation consumer, and starts the legacy execution consumer only when its
strict flag contract permits it. It owns neither compliance orchestration nor
implicit execution authority.

The shared health probe tracks worker liveness. A worker crash marks readiness
false and propagates failure. Graceful shutdown drains worker tasks and stops the
probe. Verify with execution-plane, allocation, trade runner, risk, and command
containment tests.
