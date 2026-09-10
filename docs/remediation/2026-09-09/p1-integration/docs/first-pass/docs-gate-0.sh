echo "reading-order:     success"
echo "legacy-quarantine: success"
echo "cross-references:  failure"

FAILED=0
for JOB in \
  "success" \
  "success" \
  "failure"; do
  if [[ "$JOB" != "success" ]]; then
    FAILED=1
  fi
done

if [[ "$FAILED" -eq 1 ]]; then
  echo "::error::Docs hygiene check failed"
  exit 1
fi

echo "All docs hygiene checks passed"
