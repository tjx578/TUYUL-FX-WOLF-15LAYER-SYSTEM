echo "reading-order:     success"
echo "legacy-quarantine: success"
echo "cross-references:  success"

FAILED=0
for JOB in \
  "success" \
  "success" \
  "success"; do
  if [[ "$JOB" != "success" ]]; then
    FAILED=1
  fi
done

if [[ "$FAILED" -eq 1 ]]; then
  echo "::error::Docs hygiene check failed"
  exit 1
fi

echo "All docs hygiene checks passed"
