"""Nightly walk-forward backtest worker job."""

from __future__ import annotations

from typing import Any

from loguru import logger

from config.logging_bootstrap import configure_loguru_logging
from core.redis_keys import WORKER_BACKTEST_INPUT, WORKER_BACKTEST_RESULT
from engines.walk_forward_validation_engine import WalkForwardValidator
from services.worker._job_utils import (
    load_json_payload,
    normalize_returns,
    publish_result,
    utc_now_iso,
    write_json_artifact,
)

configure_loguru_logging()


def run() -> None:
    raw_payload = load_json_payload(
        env_json_var="WOLF15_BACKTEST_RETURNS_JSON",
        env_file_var="WOLF15_BACKTEST_RETURNS_FILE",
        redis_key=WORKER_BACKTEST_INPUT,
    )
    returns = normalize_returns(raw_payload)
    if len(returns) < 130:
        logger.warning(
            "wolf15-worker nightly backtest skipped: need >=130 returns, got {}",
            len(returns),
        )
        return

    validator = WalkForwardValidator()
    result = validator.run(returns)
    payload: dict[str, Any] = {
        "job": "nightly_backtest",
        "timestamp": utc_now_iso(),
        "returns_count": len(returns),
        "result": result.to_dict(),
    }

    publish_result(WORKER_BACKTEST_RESULT, payload)
    artifact = write_json_artifact("storage/snapshots/worker/nightly_backtest_latest.json", payload)
    logger.info(
        "wolf15-worker nightly backtest completed: passed={} windows={} artifact={}",
        result.passed,
        result.window_count,
        artifact,
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("wolf15-worker nightly backtest: unhandled error in __main__: {}", exc)
