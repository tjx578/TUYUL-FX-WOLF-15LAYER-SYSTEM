#!/usr/bin/env python
"""
Lightweight health check to verify configs are readable and core modules import.
"""

import sys
from pathlib import Path

# Ensure repository root is importable when script is executed as
# `python scripts/health_check.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loguru import logger  # noqa: E402

from config_loader import load_constitution, load_prop_firm, load_settings  # noqa: E402


def main() -> int:
    try:
        settings = load_settings()
        constitution = load_constitution()
        prop = load_prop_firm()

        if not settings or not constitution or not prop:
            raise ValueError("Missing configuration payloads")

        logger.info(
            "System ready | env={} | tp_mode={}",
            settings["app"]["environment"],
            constitution["execution_rules"]["tp_mode"],
        )
        logger.info("Prop-firm guard active: {}", prop["prop_firm"]["enabled"])
        print("OK")
        return 0
    except (RuntimeError, ValueError, KeyError) as exc:  # pragma: no cover - defensive logging
        logger.error("Health check failed: {}", exc)
        print("FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
