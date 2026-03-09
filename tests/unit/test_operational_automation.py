from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ops.railway.operational_automation import (
    CanaryOrchestrator,
    CanaryStage,
    CommandResult,
    IncidentRunbookAutomation,
    default_canary_stages,
)


class FakeRunner:
    def __init__(self, mapping: dict[str, CommandResult]) -> None:
        super().__init__()
        self.mapping = mapping
        self.commands: list[str] = []

    def run(self, command: str) -> CommandResult:
        self.commands.append(command)
        return self.mapping.get(
            command,
            CommandResult(command=command, return_code=0, output="ok"),
        )


def test_default_canary_stages_order() -> None:
    stages = default_canary_stages()
    assert [stage.traffic_percent for stage in stages] == [5, 25, 50, 100]


def test_canary_deploy_success() -> None:
    runner = FakeRunner(mapping={})
    orchestrator = CanaryOrchestrator(
        runner=runner,
        sleep_fn=lambda _: None,
        healthcheck_fn=lambda _url: True,
    )

    results = orchestrator.deploy(
        service="wolf_ingest",
        stages=[CanaryStage(traffic_percent=5, soak_seconds=0)],
        deploy_cmd="deploy",
        shift_cmd_template="shift {service} {traffic_percent}",
        promote_cmd="promote",
        rollback_cmd="rollback",
        health_url="http://health",
    )

    assert len(results) == 3
    assert runner.commands == ["deploy", "shift wolf_ingest 5", "promote"]


def test_canary_deploy_health_failure_triggers_rollback() -> None:
    runner = FakeRunner(mapping={"rollback": CommandResult(command="rollback", return_code=0, output="rolled")})
    orchestrator = CanaryOrchestrator(
        runner=runner,
        sleep_fn=lambda _: None,
        healthcheck_fn=lambda _url: False,
    )

    try:
        orchestrator.deploy(
            service="wolf_execution",
            stages=[CanaryStage(traffic_percent=25, soak_seconds=0)],
            deploy_cmd="deploy",
            shift_cmd_template="shift {service} {traffic_percent}",
            promote_cmd="promote",
            rollback_cmd="rollback",
            health_url="http://health",
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "Rollback attempted" in str(exc)

    assert runner.commands[-1] == "rollback"


def test_incident_runbook_writes_report_and_audit(tmp_path: Path) -> None:
    runner = FakeRunner(
        mapping={
            "diag": CommandResult(command="diag", return_code=0, output="diagnostic ok"),
            "rollback": CommandResult(command="rollback", return_code=0, output="rollback ok"),
        }
    )

    fixed_now = datetime(2026, 3, 9, 10, 0, 0, tzinfo=UTC)
    automation = IncidentRunbookAutomation(
        runner=runner,
        healthcheck_fn=lambda _url: False,
        now_fn=lambda: fixed_now,
    )

    result = automation.execute(
        incident_key="ingest_down",
        service="wolf_ingest",
        health_urls=["http://localhost:8082/healthz"],
        diagnostic_commands=["diag"],
        rollback_command="rollback",
        auto_rollback=True,
        report_dir=tmp_path / "reports",
        audit_log_path=tmp_path / "audit.jsonl",
    )

    assert result.rollback_attempted is True
    assert result.checks_passed is False
    assert result.report_path.exists()

    report_text = result.report_path.read_text(encoding="utf-8")
    assert "Incident Runbook Report - ingest_down" in report_text
    assert "rollback ok" in report_text

    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
