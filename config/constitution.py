import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "constitution.yaml", "r") as f:
    CONSTITUTION_THRESHOLDS = yaml.safe_load(f)
