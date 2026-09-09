"""Real PostgreSQL acceptance; only explicitly marked disposable databases."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer, SignalThrottleLogEvent
from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
from contracts.strategy_5scr_activity_runtime import ActivityCoverageCheckpointV1, ActivityRuntimeBindingV1
from contracts.strategy_5scr_pair_activity import PairActivityPolicyV31
from scripts.ci.pair_activity_run_evidence import (
    evidence_directory,
    observe_postgres,
    record_runtime_fixture,
    write_fixture_phase,
)
from scripts.ci.postgres_server_binding import require_server_address
from storage.strategy_5scr_activity_runtime import ActivityRuntimeIntegrityError, PostgresActivityRuntime
from tests.integration.postgres_test_guard import (
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
)

START = datetime(2026, 9, 9, tzinfo=UTC)


@pytest.fixture(scope="module")
def pg_dsn():
    if os.environ.get("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("requires explicitly enabled disposable PostgreSQL")
    require_destructive_postgres_opt_in(os.environ.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
    dsn = os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
    expected = os.environ["WOLF15_POSTGRES_TEST_DATABASE"]
    require_disposable_postgres_target(dsn, expected_database=expected)
    assert not urlsplit(dsn).query and not urlsplit(dsn).fragment, "test DSN overrides are forbidden"
    with psycopg.connect(dsn) as connection:
        require_server_address(
            connection.execute("SELECT inet_server_addr()::text").fetchone()[0],
            os.environ.get("WOLF15_POSTGRES_TEST_SERVER_ADDRESS", ""),
        )
        assert connection.execute("SELECT current_database()").fetchone()[0] == expected
        assert (
            connection.execute("SELECT current_setting('wolf15.environment_class',true)").fetchone()[0]
            == "DISPOSABLE_TEST"
        )
        assert (
            connection.execute("SELECT current_setting('wolf15.destructive_tests_allowed',true)").fetchone()[0]
            == "true"
        )
        present = connection.execute("SELECT to_regclass('public.pair_activity_ledgers_v31')").fetchone()[0]
        assert present is not None, "explicit migrator setup must create the v3.1 schema before acceptance tests"
    strict = evidence_directory() is not None
    if strict:

        def observe():
            with psycopg.connect(dsn, connect_timeout=3, options="-c statement_timeout=5000") as connection:
                return observe_postgres(
                    connection,
                    expected,
                    os.environ["WOLF15_PAIR_ACTIVITY_EXPECTED_MIGRATION_HEAD"],
                    int(os.environ["WOLF15_PAIR_ACTIVITY_EXPECTED_PG_MAJOR"]),
                )

        write_fixture_phase("before", observe())
    yield dsn
    if strict:
        write_fixture_phase("after", observe())


def raw(second: int, direction: str = "BUY", symbol: str = "EURUSD", *, identity: str | None = None):
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=second),
        severity="info",
        message="disposable fixture",
        symbol=symbol,
        event_type="ALLOWED",
        verdict=f"EXECUTE_{direction}",
        direction=direction,
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="test-deployment",
        scanner_cycle_id=f"SCAN_{second}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
        source_observation_id=identity or f"source-{symbol}-{second}",
        source_observation_schema="signal-throttle-observation.v1",
    )


def fixture_binding(*, policy=True):
    return ActivityRuntimeBindingV1(
        ledger_id=f"test-{uuid4()}",
        deployment_id="test-deployment",
        producer_id="fixture-producer",
        source_scope_id="all-symbols-raw-fixture",
        coverage_attestor_id="fixture-independent-expected-population",
        environment_class="DISPOSABLE_TEST",
        window_start_utc=START,
        maximum_ledger_events=100,
        recovery_overlap_seconds=60,
        policy=PairActivityPolicyV31(
            policy_id="TEST_ONLY_GAP150_TTL600", maximum_source_gap_seconds=150, grant_ttl_seconds=600
        )
        if policy
        else None,
    )


def checkpoint(binding, expected_events, *, end=300, status="COMPLETE"):
    expected = normalize_pair_activity_observations(expected_events)
    return ActivityCoverageCheckpointV1(
        binding_hash=binding.binding_hash,
        attestor_id=binding.coverage_attestor_id,
        window_start_utc=START,
        window_end_utc=START + timedelta(seconds=end),
        expected_raw_count=expected.raw_event_count,
        expected_raw_hash=expected.raw_population_hash,
        status=status,
    )


def runtime(dsn, binding, cp, *, second=300, after_evaluations=None):
    record_runtime_fixture(binding, cp)
    return PostgresActivityRuntime(
        dsn=dsn,
        binding=binding,
        checkpoint_provider=lambda: cp,
        clock=lambda: START + timedelta(seconds=second),
        after_evaluations=after_evaluations,
    )


def rows(dsn, binding):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        counts = {}
        for name in ("raw", "observations", "evaluations", "attachments", "snapshots"):
            counts[name] = connection.execute(
                f"SELECT count(*) AS n FROM public.pair_activity_{name}_v31 WHERE ledger_id=%s", (binding.ledger_id,)
            ).fetchone()["n"]
        counts["ledger"] = connection.execute(
            "SELECT revision,evaluated_through,raw_watermark FROM public.pair_activity_ledgers_v31 WHERE ledger_id=%s",
            (binding.ledger_id,),
        ).fetchone()
        return counts


def assert_granted(report):
    assert report["status"] == "EVALUATED"
    assert report["persistence"]["status"] == "COMMITTED"
    evaluations = report["audit"]["evaluations"]
    assert len(evaluations) == 1
    result = evaluations[0]
    assert result["decision"] == "GRANTED" and result["duration_seconds"] == 300
    assert result["direction_quality"] == "CONFLICT"
    for key in ("hypothesis_authority", "risk_authority", "execution_authority", "valid_for_execution"):
        assert result[key] is False
    return result


def test_real_service_caller_300_seconds_restart_and_replay(pg_dsn, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ID", "test-deployment")
    binding = fixture_binding()
    # Independently create the expected producer population; do not attest the
    # contents of the consumer buffer as complete.
    producer = SignalThrottleLiveAnalyzer()
    for second, direction in ((0, "BUY"), (150, "SELL"), (300, "BUY")):
        producer.record_allowed(
            symbol="EURUSD",
            verdict=f"EXECUTE_{direction}",
            timestamp=START + timedelta(seconds=second),
            observation_id=f"source-{second}",
        )
    expected = tuple(producer._events)
    cp = checkpoint(binding, expected)
    caller = SignalThrottleLiveAnalyzer(pair_activity_runtime=runtime(pg_dsn, binding, cp))
    for second, direction in ((0, "BUY"), (150, "SELL"), (300, "BUY")):
        caller.record_allowed(
            symbol="EURUSD",
            verdict=f"EXECUTE_{direction}",
            timestamp=START + timedelta(seconds=second),
            observation_id=f"source-{second}",
        )
    before = caller.snapshot()["pair_activity_v31"]
    granted = assert_granted(before)
    assert before["normalization"]["logical_observation_count"] == 3
    restarted = SignalThrottleLiveAnalyzer(pair_activity_runtime=runtime(pg_dsn, binding, cp))
    assert not restarted._events
    assert restarted.snapshot()["pair_activity_v31"] == before
    for event in expected:
        restarted.record(event)
    assert restarted.snapshot()["pair_activity_v31"] == before
    counts = rows(pg_dsn, binding)
    assert {key: counts[key] for key in ("raw", "observations", "evaluations", "attachments", "snapshots")} == {
        "raw": 3,
        "observations": 3,
        "evaluations": 1,
        "attachments": 1,
        "snapshots": 1,
    }
    assert counts["ledger"]["raw_watermark"] == START + timedelta(seconds=300)
    assert granted["admission_id"]


def test_restart_in_fresh_python_process_reads_postgres_not_memory(pg_dsn, tmp_path):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)
    service = runtime(pg_dsn, binding, cp)
    service.append(events)
    before = service.evaluate()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"binding": binding.model_dump(mode="json"), "checkpoint": cp.model_dump(mode="json")}),
        encoding="utf-8",
    )
    program = """import json,os,sys
from datetime import datetime,UTC
from contracts.strategy_5scr_activity_runtime import ActivityRuntimeBindingV1,ActivityCoverageCheckpointV1
from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime
from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer
data=json.load(open(sys.argv[1],encoding='utf-8'))
store=PostgresActivityRuntime(dsn=os.environ['WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL'],binding=ActivityRuntimeBindingV1.model_validate(data['binding']),checkpoint_provider=lambda:ActivityCoverageCheckpointV1.model_validate(data['checkpoint']),clock=lambda:datetime(2026,9,9,0,5,tzinfo=UTC))
print(json.dumps(SignalThrottleLiveAnalyzer(pair_activity_runtime=store).snapshot()['pair_activity_v31']))
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "COMSPEC"}
    }
    env.update(
        WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL=pg_dsn,
        WOLF15_LOAD_DOTENV="false",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(request)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    assert json.loads(result.stdout) == before


def test_concurrent_connections_do_not_duplicate_activity_or_observation(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)

    def deliver(_):
        worker = runtime(pg_dsn, binding, cp)
        worker.append(events)
        return worker.evaluate()

    with ThreadPoolExecutor(max_workers=4) as executor:
        reports = list(executor.map(deliver, range(8)))
    assert all(report == reports[0] for report in reports)
    assert_granted(reports[0])
    counts = rows(pg_dsn, binding)
    assert counts["raw"] == counts["observations"] == 3
    assert counts["evaluations"] == counts["attachments"] == counts["snapshots"] == 1
    assert counts["ledger"]["revision"] == 3


def test_crash_rolls_back_outcome_attachment_and_watermark(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)

    def crash():
        raise RuntimeError("injected crash before watermark commit")

    service = runtime(pg_dsn, binding, cp, after_evaluations=crash)
    service.append(events)
    with pytest.raises(RuntimeError, match="injected crash"):
        service.evaluate()
    counts = rows(pg_dsn, binding)
    assert counts["raw"] == 3
    assert counts["evaluations"] == counts["attachments"] == counts["snapshots"] == 0
    assert counts["ledger"]["evaluated_through"] is None
    assert counts["ledger"]["raw_watermark"] is None
    assert_granted(runtime(pg_dsn, binding, cp).evaluate(trigger="RESTART_RECOVERY"))


@pytest.mark.parametrize(
    "case,reason",
    [
        ("missing_checkpoint", "INDETERMINATE_RAW_AUTHORITY_COVERAGE"),
        ("missing_policy", "PAIR_ACTIVITY_POLICY_UNBOUND"),
        ("incomplete", "INDETERMINATE_RAW_AUTHORITY_COVERAGE"),
        ("missing_population", "INDETERMINATE_RAW_AUTHORITY_COVERAGE"),
        ("gap", "SUSPENDED_SOURCE_GAP"),
    ],
)
def test_failure_cases_through_caller_persist_explicit_outcomes(pg_dsn, case, reason):
    binding = fixture_binding(policy=case != "missing_policy")
    expected = [raw(0), raw(150, "SELL"), raw(300)]
    events = [raw(0), raw(300)] if case in {"gap", "missing_population"} else expected
    cp = (
        None
        if case == "missing_checkpoint"
        else checkpoint(
            binding,
            expected if case == "missing_population" else events,
            status="INCOMPLETE" if case == "incomplete" else "COMPLETE",
        )
    )
    service = runtime(pg_dsn, binding, cp)
    caller = SignalThrottleLiveAnalyzer(pair_activity_runtime=service)
    for event in events:
        caller.record(event)
    report = caller.snapshot()["pair_activity_v31"]
    evaluation = report["audit"]["evaluations"][0]
    assert evaluation["decision"] == "SUSPENDED" and evaluation["reason_code"] == reason
    assert evaluation["admission_id"] is None
    assert rows(pg_dsn, binding)["attachments"] == 1


def test_backfill_requires_reconciliation_and_keeps_one_frozen_admission(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)
    service = runtime(pg_dsn, binding, cp)
    service.append(events)
    first = assert_granted(service.evaluate())
    changed = [*events, raw(100, "SELL")]
    service.append([changed[-1]])
    report = runtime(pg_dsn, binding, checkpoint(binding, changed)).evaluate(trigger="BACKFILL")
    current = report["audit"]["evaluations"][0]
    assert current["decision"] == "RECONCILIATION_REQUIRED"
    assert current["previous_admission_id"] == first["admission_id"] and current["admission_id"] is None
    assert rows(pg_dsn, binding)["attachments"] == 1
    assert runtime(pg_dsn, binding, checkpoint(binding, changed)).evaluate() == report


def test_conflicting_source_identity_rolls_back_raw_append(pg_dsn):
    binding = fixture_binding()
    service = runtime(pg_dsn, binding, None)
    service.append([raw(0, identity="stable")])
    with pytest.raises(ValueError):
        service.append([raw(300, identity="stable")])
    assert rows(pg_dsn, binding)["raw"] == 1


def test_immutable_ledger_binding_rejected(pg_dsn):
    binding = fixture_binding()
    service = runtime(pg_dsn, binding, None)
    service.append([raw(0)])
    changed = ActivityRuntimeBindingV1.model_validate({**binding.model_dump(mode="json"), "producer_id": "different"})
    with pytest.raises(ActivityRuntimeIntegrityError, match="BINDING_CONFLICT"):
        runtime(pg_dsn, changed, None).append([raw(150)])


@pytest.mark.parametrize("bad", [True, None, "false", "missing"])
@pytest.mark.parametrize(
    "key", ["hypothesis_authority", "risk_authority", "execution_authority", "valid_for_execution"]
)
def test_postgres_itself_rejects_authority_escalation_or_null(pg_dsn, bad, key):
    binding = fixture_binding()
    service = runtime(pg_dsn, binding, None)
    service.append([raw(0)])
    payload = dict.fromkeys(
        ["hypothesis_authority", "risk_authority", "execution_authority", "valid_for_execution"], False
    )
    payload.update(evaluation_id="invalid", activity_id="invalid")
    if bad == "missing":
        del payload[key]
    else:
        payload[key] = bad
    with psycopg.connect(pg_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO public.pair_activity_evaluations_v31(ledger_id,evaluation_id,activity_id,payload) VALUES (%s,%s,%s,%s)",
            (binding.ledger_id, "invalid", "invalid", Jsonb(payload)),
        )


def test_stale_worker_cannot_rewind_committed_watermark(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)
    service = runtime(pg_dsn, binding, cp)
    service.append(events)
    service.evaluate()
    stale = runtime(pg_dsn, binding, cp, second=299).evaluate()
    assert stale["reason_code"] == "STALE_DECISION_TIME"
    assert rows(pg_dsn, binding)["ledger"]["evaluated_through"] == START + timedelta(seconds=300)


def test_temporary_coverage_loss_recovers_original_frozen_admission(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)
    service = runtime(pg_dsn, binding, cp)
    service.append(events)
    first = assert_granted(service.evaluate())
    suspended = runtime(pg_dsn, binding, checkpoint(binding, events, status="UNKNOWN"), second=301).evaluate()
    assert suspended["audit"]["evaluations"][0]["decision"] == "SUSPENDED"
    recovered = runtime(pg_dsn, binding, cp, second=302).evaluate()
    result = assert_granted(recovered)
    assert result["admission_id"] == first["admission_id"]
    assert result["valid_until_utc"] == first["valid_until_utc"]
    assert rows(pg_dsn, binding)["attachments"] == 1


def test_incomplete_coverage_does_not_advance_covered_watermark(pg_dsn):
    binding = fixture_binding()
    events = [raw(0), raw(300)]
    service = runtime(pg_dsn, binding, None)
    service.append(events)
    report = service.evaluate()
    assert report["persistence"]["raw_watermark"] is not None
    assert report["persistence"]["covered_through_utc"] is None
    assert report["replay_required"] is True


def test_producer_twins_and_duplicate_deliveries_have_one_durable_observation(pg_dsn, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ID", "test-deployment")
    binding = fixture_binding()
    producer = SignalThrottleLiveAnalyzer()
    for second, direction in ((0, "BUY"), (150, "SELL"), (300, "BUY")):
        producer.record_throttled(
            symbol="EURUSD",
            verdict=f"EXECUTE_{direction}",
            timestamp=START + timedelta(seconds=second),
            observation_id=f"twin-{second}",
        )
    expected = tuple(producer._events)
    service = runtime(pg_dsn, binding, checkpoint(binding, expected))
    for _ in range(2):
        service.append(expected)
    assert_granted(SignalThrottleLiveAnalyzer(pair_activity_runtime=service).snapshot()["pair_activity_v31"])
    counts = rows(pg_dsn, binding)
    assert counts["raw"] == 6 and counts["observations"] == 3


@pytest.mark.parametrize("key", ["hypothesis_authority", "risk_authority", "execution_authority"])
@pytest.mark.parametrize("bad", [True, None, "false", "missing"])
def test_snapshot_database_guard_requires_boolean_false_for_all_authorities(pg_dsn, key, bad):
    binding = fixture_binding()
    runtime(pg_dsn, binding, None).append([raw(0)])
    report = dict.fromkeys(["hypothesis_authority", "risk_authority", "execution_authority"], False)
    if bad == "missing":
        del report[key]
    else:
        report[key] = bad
    with psycopg.connect(pg_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO public.pair_activity_snapshots_v31(ledger_id,snapshot_id,revision,report) VALUES (%s,%s,%s,%s)",
            (binding.ledger_id, "invalid", 0, Jsonb(report)),
        )


def test_database_authority_guards_accept_actual_boolean_false_control(pg_dsn):
    binding = fixture_binding()
    runtime(pg_dsn, binding, None).append([raw(0)])
    payload = dict.fromkeys(
        ["hypothesis_authority", "risk_authority", "execution_authority", "valid_for_execution"], False
    )
    payload.update(evaluation_id="positive", activity_id="positive")
    with psycopg.connect(pg_dsn) as connection:
        connection.execute(
            "INSERT INTO public.pair_activity_evaluations_v31(ledger_id,evaluation_id,activity_id,payload) VALUES (%s,%s,%s,%s)",
            (binding.ledger_id, "positive", "positive", Jsonb(payload)),
        )
        connection.execute(
            "INSERT INTO public.pair_activity_snapshots_v31(ledger_id,snapshot_id,revision,report) VALUES (%s,%s,%s,%s)",
            (binding.ledger_id, "positive", 0, Jsonb(payload)),
        )
