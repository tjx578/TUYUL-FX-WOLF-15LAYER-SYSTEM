if [ ! -f "docs/legacy/README.md" ]; then
  echo "::error::docs/legacy/README.md is missing — quarantine index required."
  exit 1
fi
echo "Legacy quarantine index exists."
