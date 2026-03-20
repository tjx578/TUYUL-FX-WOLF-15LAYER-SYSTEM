"""Run pytest and save output to file."""

import subprocess
import sys

try:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-x",
            "-q",
            "--timeout=30",
            "-k",
            "not slow",
            "--tb=line",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    with open("_suite_result.txt", "w", encoding="utf-8") as f:
        f.write(result.stdout)
        f.write("\n---STDERR---\n")
        f.write(result.stderr)
        f.write(f"\n---EXIT: {result.returncode}---\n")
    print(f"Done. Exit={result.returncode}. Output in _suite_result.txt")
except subprocess.TimeoutExpired as e:
    with open("_suite_result.txt", "w", encoding="utf-8") as f:
        f.write((e.stdout or b"").decode("utf-8", errors="replace"))
        f.write("\n---STDERR---\n")
        f.write((e.stderr or b"").decode("utf-8", errors="replace"))
        f.write("\n---TIMEOUT---\n")
    print("TIMEOUT after 120s. Partial output in _suite_result.txt")
    sys.exit(1)
