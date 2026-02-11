from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "constitution.yaml") as f:
    CONSTITUTION_THRESHOLDS = yaml.safe_load(f)
