"""Run Alembic while ensuring failed migrations cannot print resolved secrets."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.logging_bootstrap import redact_sensitive_log_text  # noqa: E402


def _write(stream: object, content: str) -> None:
    if content:
        stream.write(redact_sensitive_log_text(content))  # type: ignore[attr-defined]
        stream.flush()  # type: ignore[attr-defined]


def run_migrations(command: Sequence[str] | None = None) -> int:
    """Execute Alembic and relay only redacted stdout/stderr."""

    result = subprocess.run(
        list(command or (sys.executable, "-m", "alembic", "upgrade", "head")),
        check=False,
        capture_output=True,
        text=True,
    )
    _write(sys.stdout, result.stdout)
    _write(sys.stderr, result.stderr)
    return int(result.returncode)


def main() -> int:
    return run_migrations()


if __name__ == "__main__":
    raise SystemExit(main())
