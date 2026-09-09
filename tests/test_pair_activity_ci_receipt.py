from pathlib import Path

import pytest

from scripts.ci.run_pair_activity_runtime_acceptance import validate_junit


@pytest.mark.parametrize(
    "body,expected",
    [
        ("", 0),
        ("<testcase name='one' classname='t'><skipped/></testcase>", 1),
        ("<testcase name='one' classname='t'><failure/></testcase>", 1),
        ("<testcase name='one' classname='t'><error/></testcase>", 1),
        ("<testcase name='one' classname='t'/>", 2),
        ("<testcase name='one' classname='t'/><testcase name='one' classname='t'/>", 2),
    ],
)
def test_ci_rejects_missing_skipped_failed_or_duplicated_acceptance(tmp_path: Path, body: str, expected: int):
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
    with pytest.raises(ValueError):
        validate_junit(path, ["t.py::one", "t.py::two"][:expected])


def test_ci_accepts_exact_executed_cases(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text(
        "<testsuites><testsuite><testcase name='one' classname='t'/><testcase name='two' classname='t'/></testsuite></testsuites>"
    )
    assert validate_junit(path, ["t.py::one", "t.py::two"]) == {"tests": 2, "failures": 0, "errors": 0, "skipped": 0}


def test_ci_rejects_same_count_but_different_test_identity(tmp_path: Path):
    path = tmp_path / "junit.xml"
    path.write_text("<testsuites><testsuite><testcase name='wrong' classname='t'/></testsuite></testsuites>")
    with pytest.raises(ValueError):
        validate_junit(path, ["t.py::required"])


# These are offline evidence-gate tests. No PostgreSQL connection is created.
def _phase(folder, run_id, phase, **changes):
    import json

    pg = {
        "database": "wolf15_ci_test",
        "migration_heads": ["20260909_01"],
        "server_version_num": 160010,
        "server_address": "127.0.0.1",
        "server_port": 5432,
        "database_oid": "1",
    }
    pg.update(changes)
    (folder / f"postgres-{phase}.json").write_text(json.dumps({"run_id": run_id, "phase": phase, "postgres": pg}))


@pytest.mark.parametrize("change", ["missing", "nonce", "head", "version", "identity", "runtime"])
def test_fixture_receipts_reject_missing_or_unbound_database_evidence(tmp_path, change):
    import json

    from scripts.ci.pair_activity_run_evidence import validate_fixture_receipts

    run_id = "a" * 32
    _phase(tmp_path, run_id, "before")
    _phase(tmp_path, run_id, "after")
    (tmp_path / "runtime-fixtures.jsonl").write_text(json.dumps({"run_id": run_id}) + "\n")
    if change == "missing":
        (tmp_path / "postgres-after.json").unlink()
    elif change == "nonce":
        _phase(tmp_path, "b" * 32, "after")
    elif change == "head":
        _phase(tmp_path, run_id, "after", migration_heads=["old"])
    elif change == "version":
        _phase(tmp_path, run_id, "after", server_version_num=170000)
    elif change == "identity":
        _phase(tmp_path, run_id, "after", database_oid="2")
    else:
        (tmp_path / "runtime-fixtures.jsonl").write_text("")
    with pytest.raises((ValueError, OSError)):
        validate_fixture_receipts(tmp_path, run_id, "wolf15_ci_test", "20260909_01", 16)


def test_disabled_control_does_not_probe_host_capacity(monkeypatch):
    from scripts.ci import pair_activity_run_evidence as e

    monkeypatch.setattr(e, "capacity_snapshot", lambda: pytest.fail("disabled control probed capacity"))
    assert e.host_snapshot(False)["capacity"]["status"] == "NOT_MEASURED"


def test_evidence_redacts_dsn_and_password_components():
    from scripts.ci.pair_activity_run_evidence import redact

    password = "test-only-secret-value"
    dsn = f"postgresql://fixture:{password}@localhost:5432/test"
    assert password not in redact(f"error {password} via {dsn}", {"DATABASE_URL": dsn})


@pytest.mark.parametrize(
    "failure", [None, "collection", "timeout", "missing_fixture", "dirty", "capacity", "source_change"]
)
def test_runner_requires_one_complete_bound_run_and_persists_failures(tmp_path, monkeypatch, failure):
    import json
    import subprocess
    from types import SimpleNamespace

    from scripts.ci import run_pair_activity_runtime_acceptance as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "source_hashes", lambda: {"fixture": "before"})
    monkeypatch.setattr(runner, "migration_graph", lambda root: {"repository_heads": ["20260909_01"]})
    monkeypatch.setattr(
        runner,
        "host_snapshot",
        lambda enabled: {"os": "Linux", "capacity": {"below_90_percent": failure != "capacity"}},
    )
    monkeypatch.setattr(
        runner.subprocess,
        "check_output",
        lambda args, **kw: ("dirty" if failure == "dirty" else "") if "status" in args else "source-sha\n",
    )
    for key, value in {
        "WOLF15_RUN_POSTGRES_INTEGRATION": "1",
        "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS": "YES_I_UNDERSTAND",
        "WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL": "postgresql://fixture:fixture@127.0.0.1:5432/wolf15_ci_test",
        "WOLF15_POSTGRES_TEST_DATABASE": "wolf15_ci_test",
        "WOLF15_PAIR_ACTIVITY_EXPECTED_PG_MAJOR": "16",
    }.items():
        monkeypatch.setenv(key, value)

    def fake_run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1, output="must-not-leak-secret")
        if "--collect-only" in command:
            return SimpleNamespace(
                returncode=1 if failure == "collection" else 0, stdout=runner.TEST + "::test_bound\n", stderr=""
            )
        env = kwargs["env"]
        folder = Path(env["WOLF15_PAIR_ACTIVITY_EVIDENCE_DIR"])
        (folder / "tests.xml").write_text(
            '<testsuites><testsuite><testcase classname="tests.integration.test_pair_activity_runtime_postgres" name="test_bound"/></testsuite></testsuites>'
        )
        if failure != "missing_fixture":
            for phase in ("before", "after"):
                _phase(folder, env["WOLF15_PAIR_ACTIVITY_RUN_ID"], phase)
            (folder / "runtime-fixtures.jsonl").write_text(
                json.dumps({"run_id": env["WOLF15_PAIR_ACTIVITY_RUN_ID"]}) + "\n"
            )
        if failure == "source_change":
            monkeypatch.setattr(runner, "source_hashes", lambda: {"fixture": "after"})
        return SimpleNamespace(returncode=0, stdout="passed", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner.main() == (0 if failure is None else 1)
    folder = next((tmp_path / "artifacts/pair-activity-runtime").iterdir())
    receipt = json.loads((folder / "receipt.json").read_text())
    assert receipt["accepted"] is (failure is None)
    assert receipt["migration_upgrade_execution"] == "NOT_BOUND"
    assert "must-not-leak-secret" not in (folder / "receipt.json").read_text()
    assert receipt["linux_acceptance"] == ("EXECUTED_POSTGRES_SUBSET_ONLY" if failure is None else "NOT_EXECUTED")
    # A second invocation keeps the previous receipt and cannot overwrite/reuse it.
    previous = (folder / "receipt.json").read_bytes()
    runner.main()
    assert (folder / "receipt.json").read_bytes() == previous
    assert len(list((tmp_path / "artifacts/pair-activity-runtime").iterdir())) == 2


@pytest.mark.parametrize("fault", [None, "database", "address", "version", "head", "marker", "fsync", "table"])
def test_observed_database_must_match_guarded_runtime_binding(fault):
    from scripts.ci.pair_activity_run_evidence import observe_postgres

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0]

        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, sql, params=()):
            if "pg_postmaster_start_time" in sql:
                return Cursor(
                    [
                        (
                            "other" if fault == "database" else "wolf15_ci_test",
                            "test_user",
                            "10.0.0.1" if fault == "address" else "127.0.0.1",
                            5432,
                            "170000" if fault == "version" else "160010",
                            "2026-09-09T00:00:00Z",
                            "123",
                        )
                    ]
                )
            if "alembic_version" in sql:
                return Cursor([("old" if fault == "head" else "20260909_01",)])
            if "to_regclass" in sql:
                return Cursor([(None if fault == "table" else params[0],)])
            settings = {
                "fsync": "off" if fault == "fsync" else "on",
                "synchronous_commit": "on",
                "wolf15.environment_class": "LIVE" if fault == "marker" else "DISPOSABLE_TEST",
                "wolf15.destructive_tests_allowed": "true",
            }
            return Cursor([(settings.get(params[0], "fixture-setting"),)])

    if fault is None:
        observed = observe_postgres(Connection(), "wolf15_ci_test", "20260909_01", 16)
        assert observed["server_version_num"] == 160010
        assert observed["migration_heads"] == ["20260909_01"]
    else:
        with pytest.raises(ValueError, match="POSTGRES_EVIDENCE_BINDING_REJECTED"):
            observe_postgres(Connection(), "wolf15_ci_test", "20260909_01", 16)


def test_migration_graph_records_structure_without_claiming_execution():
    from scripts.ci.pair_activity_run_evidence import migration_graph

    graph = migration_graph(Path(__file__).resolve().parents[1])
    assert graph["repository_heads"] == ["20260909_04"]
    assert graph["revision_parents"]["20260909_04"] == "20260909_03"
    assert graph["revision_parents"]["20260909_01"] == "20260822_01"
    assert graph["migration_upgrade_execution"] == "NOT_BOUND"


def test_source_manifest_uses_committed_selected_ssot_copy():
    from scripts.ci.run_pair_activity_runtime_acceptance import source_hashes

    hashes = source_hashes()
    assert (
        hashes["docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md"]
        == "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"
    )
    assert "conftest.py" in hashes
    assert ".github/workflows/ci.yml" in hashes
