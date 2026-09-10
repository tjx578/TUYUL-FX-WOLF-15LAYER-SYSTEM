"""
Copies all source files from dashboard/nextjs/src/ into the root src/,
preserving directory structure.  Files already written by hand-crafted
previous steps are SKIPPED so we don't clobber them.

Run with:  uv run scripts/migrate_src.py
"""

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "dashboard" / "nextjs" / "src"
DEST   = PROJECT_ROOT / "src"

# Files we already hand-crafted — keep them untouched.
SKIP = {
    "app/globals.css",
    "app/layout.tsx",
    "shared/styles/tokens.css",
    "shared/styles/primitives.css",
    "components/ClientOnly.tsx",
}

copied  = 0
skipped = 0
errors  = 0

for src_path in SOURCE.rglob("*"):
    if src_path.is_dir():
        continue

    rel = src_path.relative_to(SOURCE)
    rel_str = rel.as_posix()

    if rel_str in SKIP:
        print(f"  [SKIP]   {rel_str}")
        skipped += 1
        continue

    dest_path = DEST / rel
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(src_path, dest_path)
        print(f"  [COPY]   {rel_str}")
        copied += 1
    except Exception as e:
        print(f"  [ERROR]  {rel_str}: {e}")
        errors += 1

print()
print(f"[migrate_src] Done — {copied} copied, {skipped} skipped, {errors} errors.")
print(f"[migrate_src] Source : {SOURCE}")
print(f"[migrate_src] Dest   : {DEST}")
