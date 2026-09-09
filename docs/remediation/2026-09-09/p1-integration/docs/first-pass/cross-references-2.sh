python - <<'PYEOF'
import pathlib, re, sys

ARCH_DIR = pathlib.Path("docs/architecture")
LINK_RE = re.compile(r'\[.*?\]\((?!https?://|#)([^)]+)\)')

errors = []
for md in ARCH_DIR.rglob("*.md"):
    text = md.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        for m in LINK_RE.finditer(line):
            target = m.group(1).split("#")[0]
            if not target:
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{md}:{i} -> {target} (not found)")

if errors:
    print("Broken cross-references in docs/architecture/:")
    for e in errors[:30]:
        print(f"  {e}")
    sys.exit(1)
print(f"Checked {sum(1 for _ in ARCH_DIR.rglob('*.md'))} files — no broken links.")
PYEOF
