"""Nightly Monte Carlo worker job.

Runs portfolio-level Monte Carlo simulation from persisted return matrix.
This is analysis-only and publishes advisory metrics.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger
from config.logging_bootstrap import configure_loguru_logging

from engines.portfolio_monte_carlo_engine import PortfolioMonteCarloEngine
from services.worker._job_utils import (
    load_json_payload,
    normalize_return_matrix,
    publish_result,
    utc_now_iso,
    write_json_artifact,
)


configure_loguru_logging()


def _build_engine() -> PortfolioMonteCarloEngine:
    simulations = int(os.getenv("WOLF15_MC_SIMULATIONS", "1000"))
    seed_raw = os.getenv("WOLF15_MC_SEED", "42")
    seed = int(seed_raw) if seed_raw.strip() else None
    return PortfolioMonteCarloEngine(simulations=simulations, seed=seed)


def run() -> None:
    raw_payload = load_json_payload(
        env_json_var="WOLF15_MC_RETURN_MATRIX_JSON",
        env_file_var="WOLF15_MC_RETURN_MATRIX_FILE",
        redis_key="WOLF15:RETURN_MATRIX",
    )
    return_matrix = normalize_return_matrix(raw_payload)
    if len(return_matrix) < 2:
        logger.warning(
            "wolf15-worker montecarlo skipped: need >=2 pairs, got {}",
            len(return_matrix),
        )
        return

    engine = _build_engine()
    result = engine.run(return_matrix)
    payload: dict[str, Any] = {
        "job": "montecarlo",
        "timestamp": utc_now_iso(),
        "input_pairs": sorted(return_matrix.keys()),
        "result": result.to_dict(),
    }

    publish_result("WOLF15:WORKER:MONTE_CARLO:LAST_RESULT", payload)
    artifact = write_json_artifact("storage/snapshots/worker/montecarlo_latest.json", payload)
    logger.info(
        "wolf15-worker montecarlo completed: passed={} pairs={} artifact={}",
        result.passed_threshold,
        len(return_matrix),
        artifact,
    )


if __name__ == "__main__":
    run()
