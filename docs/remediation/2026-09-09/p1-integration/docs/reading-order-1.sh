echo "Checking docs/architecture/README.md reading order..."

READING_ORDER=(
  "data-flow.md"
  "system-overview.md"
  "dashboard-control-surface.md"
  "runtime-topology-current.md"
  "engine-lineage-zones.md"
  "config-resolver.md"
  "lock-enforcement.md"
  "config-governance.md"
  "risk-stack.md"
  "risk-monitor.md"
  "deployment-railway.md"
  "topology.md"
)

MISSING=0
for DOC in "${READING_ORDER[@]}"; do
  if [ ! -f "docs/architecture/$DOC" ]; then
    echo "::error::Reading-order entry missing: docs/architecture/$DOC"
    MISSING=1
  else
    echo "  OK: $DOC"
  fi
done

if [ "$MISSING" -eq 1 ]; then
  echo "Add the missing file(s) or update the reading order in docs/architecture/README.md"
  exit 1
fi
echo "All reading-order entries resolve."
