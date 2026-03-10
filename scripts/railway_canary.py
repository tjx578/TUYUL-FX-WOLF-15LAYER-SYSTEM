from __future__ import annotations

import argparse
import sys

from ops.railway.operational_automation import (
    CanaryOrchestrator,
    default_canary_stages,
    resolve_service_config,
)


def _validate_required(config: dict[str, str], required_keys: list[str]) -> list[str]:
    return [key for key in required_keys if not config.get(key)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Canary deployment automation for ingest/execution services")
    parser.add_argument("--service", choices=["wolf_ingest", "wolf_execution"], required=True)
    parser.add_argument("--action", choices=["deploy", "promote", "rollback"], required=True)
    parser.add_argument("--health-url", default="", help="Override service health URL")
    args = parser.parse_args()

    config = resolve_service_config(args.service)
    if args.health_url:
        config["health_url"] = args.health_url

    orchestrator = CanaryOrchestrator()

    try:
        if args.action == "deploy":
            missing = _validate_required(config, ["deploy_cmd", "shift_cmd", "promote_cmd", "rollback_cmd"])
            if missing:
                raise ValueError(f"Missing canary command configuration: {', '.join(missing)}")

            orchestrator.deploy(
                service=args.service,
                stages=default_canary_stages(),
                deploy_cmd=config["deploy_cmd"],
                shift_cmd_template=config["shift_cmd"],
                promote_cmd=config["promote_cmd"],
                rollback_cmd=config["rollback_cmd"],
                health_url=config.get("health_url") or None,
            )
            print(f"Canary deploy succeeded for {args.service}")
            return 0

        if args.action == "promote":
            missing = _validate_required(config, ["promote_cmd"])
            if missing:
                raise ValueError(f"Missing canary command configuration: {', '.join(missing)}")
            orchestrator.promote(config["promote_cmd"])
            print(f"Canary promote succeeded for {args.service}")
            return 0

        missing = _validate_required(config, ["rollback_cmd"])
        if missing:
            raise ValueError(f"Missing canary command configuration: {', '.join(missing)}")
        orchestrator.rollback(config["rollback_cmd"])
        print(f"Canary rollback succeeded for {args.service}")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"Canary automation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
