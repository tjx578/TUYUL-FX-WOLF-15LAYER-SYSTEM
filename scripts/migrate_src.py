# /// script
# requires-python = ">=3.11"
# ///
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "dashboard" / "nextjs" / "src"
DEST   = PROJECT_ROOT / "src"

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
        print("  [SKIP]   " + rel_str)
        skipped += 1
        continue

    dest_path = DEST / rel
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(src_path, dest_path)
        print("  [COPY]   " + rel_str)
        copied += 1
    except Exception as e:
        print("  [ERROR]  " + rel_str + ": " + str(e))
        errors += 1

print("")
print("[migrate_src] Done - " + str(copied) + " copied, " + str(skipped) + " skipped, " + str(errors) + " errors.")
print("[migrate_src] Source : " + str(SOURCE))
print("[migrate_src] Dest   : " + str(DEST))
