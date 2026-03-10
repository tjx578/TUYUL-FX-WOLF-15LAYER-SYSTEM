from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib import error, request

from journal.audit_trail import AuditAction, AuditTrail


@dataclass(frozen=True)
class CanaryStage:
    traffic_percent: int
    soak_seconds: int


@dataclass(frozen=True)
class CommandResult:
    command: str
    return_code: int
    output: str


class RunnerProtocol(Protocol):
    def run(self, command: str) -> CommandResult:
        ...


def http_healthcheck(url: str) -> bool:
    try:
        with request.urlopen(url, timeout=10) as response:  # noqa: S310
            return 200 <= int(response.status) < 300
    except (error.URLError, TimeoutError):
        return False


class CommandRunner:
    def run(self, command: str) -> CommandResult:
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return CommandResult(command=command, return_code=completed.returncode, output=output.strip())


def default_canary_stages() -> list[CanaryStage]:
    return [
        CanaryStage(traffic_percent=5, soak_seconds=30),
        CanaryStage(traffic_percent=25, soak_seconds=60),
        CanaryStage(traffic_percent=50, soak_seconds=120),
        CanaryStage(traffic_percent=100, soak_seconds=0),
    ]


class CanaryOrchestrator:
    def __init__(
        self,
        *,
        runner: RunnerProtocol | None = None,
        sleep_fn: Callable[[int], None] | None = None,
        healthcheck_fn: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner or CommandRunner()
        self._sleep_fn = sleep_fn or time.sleep
        self._healthcheck_fn = healthcheck_fn or http_healthcheck

    def deploy(
        self,
        *,
        service: str,
        stages: Iterable[CanaryStage],
        deploy_cmd: str,
        shift_cmd_template: str,
        promote_cmd: str,
        rollback_cmd: str,
        health_url: str | None,
    ) -> list[CommandResult]:
        results: list[CommandResult] = []

        results.append(self._run_or_raise(deploy_cmd, "deploy canary"))

        for stage in stages:
            shift_cmd = shift_cmd_template.format(
                service=service,
                traffic_percent=stage.traffic_percent,
            )
            results.append(self._run_or_raise(shift_cmd, f"shift traffic to {stage.traffic_percent}%"))

            if health_url and not self._healthcheck_fn(health_url):
                rollback_result = self._runner.run(rollback_cmd)
                results.append(rollback_result)
                raise RuntimeError(
                    f"Canary failed healthcheck at {stage.traffic_percent}% traffic. "
                    f"Rollback attempted with rc={rollback_result.return_code}."
                )

            if stage.soak_seconds > 0:
                self._sleep_fn(stage.soak_seconds)

        results.append(self._run_or_raise(promote_cmd, "promote canary"))
        return results

    def promote(self, command: str) -> CommandResult:
        return self._run_or_raise(command, "promote canary")

    def rollback(self, command: str) -> CommandResult:
        return self._run_or_raise(command, "rollback canary")

    def _run_or_raise(self, command: str, action: str) -> CommandResult:
        result = self._runner.run(command)
        if result.return_code != 0:
            raise RuntimeError(f"Failed to {action}: `{command}` -> {result.output}")
        return result

@dataclass(frozen=True)
class IncidentResult:
    report_path: Path
    rollback_attempted: bool
    checks_passed: bool


class IncidentRunbookAutomation:
    def __init__(
        self,
        *,
        runner: RunnerProtocol | None = None,
        healthcheck_fn: Callable[[str], bool] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner or CommandRunner()
        self._healthcheck_fn = healthcheck_fn or http_healthcheck
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def execute(
        self,
        *,
        incident_key: str,
        service: str,
        health_urls: Iterable[str],
        diagnostic_commands: Iterable[str],
        rollback_command: str | None,
        auto_rollback: bool,
        report_dir: Path,
        audit_log_path: Path | None,
    ) -> IncidentResult:
        checks: list[tuple[str, bool]] = [(url, self._healthcheck_fn(url)) for url in health_urls]
        checks_passed = all(ok for _, ok in checks) if checks else True

        diagnostics: list[CommandResult] = [self._runner.run(cmd) for cmd in diagnostic_commands]

        rollback_attempted = False
        rollback_result: CommandResult | None = None
        if auto_rollback and rollback_command and not checks_passed:
            rollback_result = self._runner.run(rollback_command)
            rollback_attempted = True

        report_path = self._write_report(
            incident_key=incident_key,
            service=service,
            checks=checks,
            diagnostics=diagnostics,
            rollback=rollback_result,
            report_dir=report_dir,
        )

        if audit_log_path is not None:
            trail = AuditTrail(log_path=audit_log_path)
            trail.log(
                AuditAction.SYSTEM_VIOLATION,
                actor="system:runbook",
                resource=f"incident:{incident_key}",
                details={
                    "service": service,
                    "checks_passed": checks_passed,
                    "rollback_attempted": rollback_attempted,
                    "report_path": str(report_path),
                },
            )

        return IncidentResult(
            report_path=report_path,
            rollback_attempted=rollback_attempted,
            checks_passed=checks_passed,
        )

    def _write_report(
        self,
        *,
        incident_key: str,
        service: str,
        checks: list[tuple[str, bool]],
        diagnostics: list[CommandResult],
        rollback: CommandResult | None,
        report_dir: Path,
    ) -> Path:
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self._now_fn().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"{timestamp}_{incident_key}_{service}.md"

        lines = [
            f"# Incident Runbook Report - {incident_key}",
            "",
            f"- Timestamp: {self._now_fn().isoformat()}",
            f"- Service: {service}",
            "",
            "## Health Checks",
        ]

        if checks:
            for url, ok in checks:
                lines.append(f"- {'PASS' if ok else 'FAIL'} {url}")
        else:
            lines.append("- No health checks configured")

        lines.extend(["", "## Diagnostics"])
        if diagnostics:
            for item in diagnostics:
                lines.append(f"### `{item.command}`")
                lines.append("")
                lines.append("```text")
                lines.append(item.output or "<no output>")
                lines.append("```")
        else:
            lines.append("- No diagnostic commands configured")

        lines.extend(["", "## Rollback"])
        if rollback is None:
            lines.append("- Rollback not executed")
        else:
            status = "SUCCESS" if rollback.return_code == 0 else "FAILED"
            lines.append(f"- Rollback {status}: `{rollback.command}`")
            lines.append("```text")
            lines.append(rollback.output or "<no output>")
            lines.append("```")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path


def resolve_service_config(service: str) -> dict[str, str]:
    normalized = service.upper().replace("-", "_")
    prefix = f"{normalized}_CANARY_"

    deploy_cmd = os.getenv(f"{prefix}DEPLOY_CMD") or os.getenv("CANARY_DEPLOY_CMD", "")
    shift_cmd = os.getenv(f"{prefix}SHIFT_CMD") or os.getenv("CANARY_SHIFT_CMD", "")
    promote_cmd = os.getenv(f"{prefix}PROMOTE_CMD") or os.getenv("CANARY_PROMOTE_CMD", "")
    rollback_cmd = os.getenv(f"{prefix}ROLLBACK_CMD") or os.getenv("CANARY_ROLLBACK_CMD", "")

    return {
        "deploy_cmd": deploy_cmd,
        "shift_cmd": shift_cmd,
        "promote_cmd": promote_cmd,
        "rollback_cmd": rollback_cmd,
        "health_url": os.getenv(f"{prefix}HEALTH_URL", ""),
    }
