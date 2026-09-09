echo "Scanning production code for docs/legacy references..."
VIOLATIONS=$(grep -rn "docs/legacy" \
  --include="*.py" \
  --exclude-dir=tests \
  --exclude-dir=__pycache__ \
  --exclude-dir=.venv \
  --exclude-dir=node_modules \
  . || true)
if [ -n "$VIOLATIONS" ]; then
  echo "::error::Production code references docs/legacy/:"
  echo "$VIOLATIONS"
  echo "Legacy docs are for historical traceability only — do not reference in code."
  exit 1
fi
echo "No legacy doc references in production code."
