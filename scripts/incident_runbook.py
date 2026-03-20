from __future__ import annotations

import argparse
from pathlib import Path

from ops.railway.operational_automation import IncidentRunbookAutomation


def _default_health_urls(service: str) -> list[str]:
    if service == "wolf_ingest":
        return ["http://localhost:8082/healthz"]
    if service == "wolf_execution":
        # Execution worker has metrics endpoint, no native health endpoint.
        return ["http://localhost:9103/"]
    return []


def _default_diagnostics(service: str) -> list[str]:
    return [
        f"railway logs --service {service} --lines 200",
        "railway status",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated incident runbook for Railway services")
    parser.add_argument("--incident", required=True, help="Incident key, e.g. ingest_down")
    parser.add_argument("--service", choices=["wolf_ingest", "wolf_execution"], required=True)
    parser.add_argument("--auto-rollback", action="store_true")
    parser.add_argument("--rollback-command", default="")
    parser.add_argument("--report-dir", default="storage/incidents")
    parser.add_argument("--audit-log", default="storage/audit/incident_audit.jsonl")
    args = parser.parse_args()

    automation = IncidentRunbookAutomation()
    result = automation.execute(
        incident_key=args.incident,
        service=args.service,
        health_urls=_default_health_urls(args.service),
        diagnostic_commands=_default_diagnostics(args.service),
        rollback_command=args.rollback_command or None,
        auto_rollback=args.auto_rollback,
        report_dir=Path(args.report_dir),
        audit_log_path=Path(args.audit_log),
    )

    print(f"Runbook report: {result.report_path}")
    print(f"Checks passed: {result.checks_passed}")
    print(f"Rollback attempted: {result.rollback_attempted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
