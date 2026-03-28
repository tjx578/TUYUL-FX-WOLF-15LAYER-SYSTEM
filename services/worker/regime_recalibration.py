"""Regime recalibration worker job.

Feeds volatility-ratio samples into RegimeAutoTuner and materializes
updated thresholds artifact.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from config.logging_bootstrap import configure_loguru_logging
from core.redis_keys import WORKER_REGIME_INPUT, WORKER_REGIME_RESULT
from services.worker._job_utils import (
    load_json_payload,
    normalize_returns,
    publish_result,
    read_json_artifact,
    utc_now_iso,
    write_json_artifact,
)
from utils.regime_auto_tuner import RegimeAutoTuner

configure_loguru_logging()


def run() -> None:
    raw_payload = load_json_payload(
        env_json_var="WOLF15_REGIME_VR_JSON",
        env_file_var="WOLF15_REGIME_VR_FILE",
        redis_key=WORKER_REGIME_INPUT,
    )
    vr_values = normalize_returns(raw_payload)
    if len(vr_values) < 30:
        logger.warning(
            "wolf15-worker regime recalibration skipped: need >=30 vr values, got {}",
            len(vr_values),
        )
        return

    tuner = RegimeAutoTuner(window_size=max(500, len(vr_values)), update_interval=3600)
    for vr in vr_values:
        tuner.add_vr(vr)
    tuner.tune_and_update()

    # Read recalibrated thresholds — Redis primary, filesystem fallback.
    recalibrated = read_json_artifact("config/thresholds.auto.json") or {}

    payload: dict[str, Any] = {
        "job": "regime_recalibration",
        "timestamp": utc_now_iso(),
        "vr_count": len(vr_values),
        "recalibrated": recalibrated,
    }

    publish_result(WORKER_REGIME_RESULT, payload)
    artifact = write_json_artifact("storage/snapshots/worker/regime_recalibration_latest.json", payload)
    logger.info(
        "wolf15-worker regime recalibration completed: vr_count={} artifact={}",
        len(vr_values),
        artifact,
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        logger.exception("wolf15-worker regime recalibration: unhandled error in __main__: {}", exc)
