"""Nightly Monte Carlo worker job.

Runs portfolio-level Monte Carlo simulation from persisted return matrix.
This is analysis-only and publishes advisory metrics.
Enforces the constitutional monte_min threshold from config/constitution.yaml.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from loguru import logger

# Configure logging FIRST — before any other imports that may trigger logging —
# so that startup crashes are always captured and visible in Railway logs.
from config.logging_bootstrap import configure_loguru_logging
from core.redis_keys import WORKER_MC_INPUT, WORKER_MC_RESULT

configure_loguru_logging()

from engines.portfolio_monte_carlo_engine import PortfolioMonteCarloEngine  # noqa: E402
from pipeline.constants import get_monte_min  # noqa: E402
from services.worker._job_utils import (  # noqa: E402
    load_json_payload,
    normalize_return_matrix,
    publish_result,
    utc_now_iso,
    write_json_artifact,
)


def _build_engine() -> PortfolioMonteCarloEngine:
    simulations = int(os.getenv("WOLF15_MC_SIMULATIONS", "1000"))
    seed_raw = os.getenv("WOLF15_MC_SEED", "42")
    seed = int(seed_raw) if seed_raw.strip() else None
    monte_min = get_monte_min()
    return PortfolioMonteCarloEngine(
        simulations=simulations,
        seed=seed,
        win_threshold=monte_min,
    )


def _validate_startup() -> bool:
    """Check that the job has at least one viable data source before running.

    Returns ``True`` when the job should proceed, ``False`` when all data
    sources are absent and the job should skip gracefully.

    Diagnostics are logged at WARNING level so they always appear in Railway
    even when the container otherwise has no output.
    """
    sources: list[str] = []

    if (os.getenv("WOLF15_MC_RETURN_MATRIX_JSON") or "").strip():
        sources.append("WOLF15_MC_RETURN_MATRIX_JSON (inline JSON)")

    if (os.getenv("WOLF15_MC_RETURN_MATRIX_FILE") or "").strip():
        sources.append(f"WOLF15_MC_RETURN_MATRIX_FILE ({os.getenv('WOLF15_MC_RETURN_MATRIX_FILE')})")

    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        sources.append("WOLF15:RETURN_MATRIX (Redis)")
    else:
        logger.warning("[Startup] REDIS_URL not set — Redis data source unavailable for montecarlo_job")

    if not sources:
        logger.warning(
            "[Startup] No data sources configured for montecarlo_job. "
            "Set one of: WOLF15_MC_RETURN_MATRIX_JSON, WOLF15_MC_RETURN_MATRIX_FILE, "
            "or REDIS_URL with WOLF15:RETURN_MATRIX key. Job will skip this cycle."
        )
        return False

    logger.info("[Startup] montecarlo_job data sources: {}", ", ".join(sources))
    return True


def run() -> None:
    """Execute the Monte Carlo simulation job.

    Handles all exceptions internally so the ``while true`` bash loop in
    Railway does not exit — the container stays alive and retries next cycle.
    """
    try:
        raw_payload = load_json_payload(
            env_json_var="WOLF15_MC_RETURN_MATRIX_JSON",
            env_file_var="WOLF15_MC_RETURN_MATRIX_FILE",
            redis_key=WORKER_MC_INPUT,
        )
        if raw_payload is None:
            logger.warning(
                "wolf15-worker montecarlo skipped: no return matrix data available "
                "(WOLF15:RETURN_MATRIX not found in any data source)"
            )
            return

        return_matrix = normalize_return_matrix(raw_payload)
        if len(return_matrix) < 2:
            logger.warning(
                "wolf15-worker montecarlo skipped: need >=2 pairs, got {}",
                len(return_matrix),
            )
            return

        monte_min = get_monte_min()
        engine = _build_engine()
        result = engine.run(return_matrix)

        payload: dict[str, Any] = {
            "job": "montecarlo",
            "timestamp": utc_now_iso(),
            "input_pairs": sorted(return_matrix.keys()),
            "monte_min_threshold": monte_min,
            "passed_threshold": result.passed_threshold,
            "portfolio_win_probability": result.portfolio_win_probability,
            "result": result.to_dict(),
        }

        publish_result(WORKER_MC_RESULT, payload)
        artifact = write_json_artifact("storage/snapshots/worker/montecarlo_latest.json", payload)

        if not result.passed_threshold:
            logger.warning(
                "wolf15-worker montecarlo FAILED threshold: "
                "portfolio_win_prob={:.4f} < monte_min={:.2f} — "
                "L7 gate will block EXECUTE verdicts until recalibration.",
                result.portfolio_win_probability,
                monte_min,
            )
        else:
            logger.info(
                "wolf15-worker montecarlo PASSED: "
                "portfolio_win_prob={:.4f} >= monte_min={:.2f}, pairs={}, artifact={}",
                result.portfolio_win_probability,
                monte_min,
                len(return_matrix),
                artifact,
            )
    except Exception as exc:
        logger.exception(
            "wolf15-worker montecarlo CRASHED (will retry next cycle): {}",
            exc,
        )


if __name__ == "__main__":
    try:
        if _validate_startup():
            run()
        else:
            logger.info("wolf15-worker montecarlo: startup validation failed — skipping cycle")
    except Exception as exc:
        logger.exception("wolf15-worker montecarlo: unhandled error in __main__: {}", exc)
        sys.exit(0)  # exit 0 so the bash retry loop continues
