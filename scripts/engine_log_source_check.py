"""Check ENGINE_LOG_SOURCE_URL connectivity.

This is intentionally small and dependency-free so it can run inside the same
container/service environment as an external SignalThrottle sidecar.

Usage:
    python scripts/engine_log_source_check.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _load_env() -> None:
    if "ENGINE_LOG_SOURCE_URL" in os.environ:
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    url = os.environ.get("ENGINE_LOG_SOURCE_URL", "").strip()
    if not url:
        print("[FATAL] ENGINE_LOG_SOURCE_URL is not set.")
        print("        Example: ENGINE_LOG_SOURCE_URL=http://wolf-engine:8081/healthz")
        return 1

    headers: dict[str, str] = {"Accept": "application/json"}
    token = os.environ.get("HEALTH_PROBE_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            print(f"[OK] {url} -> HTTP {resp.status}")
            try:
                print(json.dumps(json.loads(body), indent=2, sort_keys=True))
            except json.JSONDecodeError:
                print(body[:500])
            return 0 if 200 <= resp.status < 300 else 2
    except urllib.error.HTTPError as exc:
        body = exc.read(1024).decode("utf-8", errors="replace")
        print(f"[HTTP] {url} -> HTTP {exc.code}")
        print(body[:500])
        return 2
    except Exception as exc:
        print(f"[FAIL] {url} unreachable: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
