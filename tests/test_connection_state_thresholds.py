"""Freshness behavior for the selected Railway dashboard presentation model.

The retired Vercel connectionState.ts owned hardcoded per-domain thresholds.
The Railway viewer requires an explicit source policy instead: missing policy
stays NOT_MEASURED, source staleness is preserved, and age limits are enforced.
These executable model tests replace the removed-file constant assertions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "dashboard/nextjs/src/components/wolf15-v2/model.mjs"
NOW = 1_700_000_100_000


def observation(**changes):
    value = {
        "state": "ready",
        "asOf": "2023-11-14T22:13:20.000Z",
        "freshness": {"state": "FRESH", "policyId": "fixture-policy", "maxAgeMs": 100_000},
    }
    value.update(changes)
    return value


@pytest.mark.parametrize(
    ("value", "now", "expected"),
    [
        pytest.param(None, NOW, "NOT_MEASURED", id="absent-observation"),
        pytest.param(observation(state="error"), NOW, "NOT_MEASURED", id="failed-observation"),
        pytest.param(observation(state="not_connected"), NOW, "NOT_MEASURED", id="disconnected"),
        pytest.param(observation(asOf=None), NOW, "NOT_MEASURED", id="missing-timestamp"),
        pytest.param(observation(asOf="invalid"), NOW, "NOT_MEASURED", id="invalid-timestamp"),
        pytest.param(observation(), NOW - 100_001, "NOT_MEASURED", id="future-timestamp"),
        pytest.param(observation(freshness={"state": "STALE"}), NOW, "STALE", id="source-stale-preserved"),
        pytest.param(
            observation(freshness={"state": "STALE_PRESERVED"}), NOW, "STALE_PRESERVED", id="source-preserved-state"
        ),
        pytest.param(observation(freshness={"state": "NOT_MEASURED"}), NOW, "NOT_MEASURED", id="source-not-measured"),
        pytest.param(
            observation(freshness={"state": "FRESH", "maxAgeMs": 100_000}), NOW, "NOT_MEASURED", id="policy-id-required"
        ),
        pytest.param(
            observation(freshness={"state": "FRESH", "policyId": "fixture-policy"}),
            NOW,
            "NOT_MEASURED",
            id="limit-required",
        ),
        pytest.param(
            observation(freshness={"state": "FRESH", "policyId": "fixture-policy", "maxAgeMs": "100000"}),
            NOW,
            "NOT_MEASURED",
            id="numeric-limit-required",
        ),
        pytest.param(
            observation(freshness={"state": "FRESH", "policyId": "fixture-policy", "maxAgeMs": 0}),
            NOW,
            "NOT_MEASURED",
            id="positive-limit-required",
        ),
        pytest.param(observation(), NOW, "FRESH", id="exact-age-boundary"),
        pytest.param(observation(), NOW + 1, "STALE", id="expired-by-one-millisecond"),
    ],
)
def test_railway_freshness_requires_observed_source_policy(value, now, expected):
    node = shutil.which("node")
    assert node is not None, "Node.js is required to execute the selected Railway model contract"
    script = (
        "import {freshness} from "
        + json.dumps(MODEL.as_uri())
        + "; console.log(JSON.stringify(freshness(JSON.parse(process.argv[1]), Number(process.argv[2]))));"
    )
    env = {
        key: val for key, val in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, json.dumps(value), str(now)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == expected
