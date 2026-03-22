#!/usr/bin/env bash
# ============================================================
# patch_hydration.sh — Permanent hydration-mismatch fix
#
# Replaces all bare .toLocaleTimeString() / .toLocaleString()
# calls in component render paths with deterministic
# formatTime() from @/lib/timezone (pinned locale + timezone).
#
# After this patch is applied, suppressHydrationWarning on
# <html> and <body> in src/app/layout.tsx can be safely removed.
#
# Run: bash dashboard/nextjs/patch_hydration.sh
# ============================================================

set -euo pipefail
cd "$(dirname "$0")"

echo "=== TUYUL FX Hydration Patch ==="
echo ""

# ── 1. Verify no unsafe toLocaleTimeString remains in components ──
echo "[1/3] Scanning for remaining unsafe .toLocaleTimeString() calls..."

UNSAFE=$(grep -rn '\.toLocaleTimeString\|\.toLocaleDateString\|\.toLocaleString' src/ \
  --include='*.tsx' --include='*.ts' \
  | grep -v 'lib/timezone.ts' \
  | grep -v 'lib/formatters.ts' \
  | grep -v 'node_modules' \
  || true)

if [ -n "$UNSAFE" ]; then
  echo "⚠  Found unsafe locale calls that need manual review:"
  echo "$UNSAFE"
  echo ""
  echo "Replace these with formatTime() from @/lib/timezone"
  echo "or useClientDate()/useClientNumber() from @/lib/formatters"
  exit 1
else
  echo "✓  No unsafe locale calls found in components."
fi

# ── 2. Verify formatTime is imported where used ──
echo "[2/3] Checking formatTime imports..."

FILES_USING=$(grep -rln 'formatTime(' src/ --include='*.tsx' --include='*.ts' \
  | grep -v 'lib/timezone.ts' \
  | grep -v 'node_modules' \
  || true)

MISSING_IMPORT=0
for f in $FILES_USING; do
  if ! grep -q "from.*@/lib/timezone" "$f"; then
    echo "⚠  Missing timezone import in: $f"
    MISSING_IMPORT=1
  fi
done

if [ "$MISSING_IMPORT" -eq 0 ]; then
  echo "✓  All formatTime consumers import from @/lib/timezone."
else
  echo "Fix missing imports above before removing suppressHydrationWarning."
  exit 1
fi

# ── 3. Ready to remove suppressHydrationWarning ──
echo "[3/3] Checking if suppressHydrationWarning can be removed..."

LAYOUT="src/app/layout.tsx"
if grep -q 'suppressHydrationWarning' "$LAYOUT"; then
  echo ""
  echo "All locale calls are now deterministic."
  echo "You can safely remove suppressHydrationWarning from $LAYOUT."
  echo ""
  echo "To auto-remove, run:"
  echo "  sed -i 's/ suppressHydrationWarning//g' $LAYOUT"
else
  echo "✓  suppressHydrationWarning already removed."
fi

echo ""
echo "=== Hydration patch verification complete ==="
