"""Scan for remaining hardcoded wolf15: keys outside the registry."""

import os

EXCLUDES = {
    "core/redis_keys.py",
    "state/redis_keys.py",
    "state/pubsub_channels.py",
    "state/channels.py",
    "state/consumer_groups.py",
}
EXCLUDE_DIRS = {
    "tests",
    "docs",
    "config",
    "__pycache__",
    ".git",
    "node_modules",
    "dashboard",
    "migrations",
    "scripts",
    "deploy",
    "incidents",
    "ops",
    ".ruff_cache",
}

results = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for fn in files:
        if not fn.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.join(root, fn), ".").replace("\\", "/")
        if rel in EXCLUDES:
            continue
        if rel.startswith("_"):
            continue
        with open(os.path.join(root, fn), encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                if "wolf15:" not in stripped.lower():
                    continue
                # Skip comments, log lines, docstrings
                if stripped.startswith("#"):
                    continue
                if stripped.startswith(("logger.", "log.")):
                    continue
                if stripped.startswith(('"""', "'''")):
                    continue
                # Only flag assignments, f-strings, and direct string defs
                if any(kw in stripped for kw in ("=", "stream=", "key=")):
                    results.append(f"{rel}:{i}: {stripped[:140]}")

for r in sorted(results):
    print(r)
print(f"\n--- Total: {len(results)} potential hardcoded wolf15: keys ---")
