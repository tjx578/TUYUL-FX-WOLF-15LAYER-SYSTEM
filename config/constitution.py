from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

_CONSTITUTION_PATH = Path(__file__).with_suffix(".yaml")

with _CONSTITUTION_PATH.open("r", encoding="utf-8") as handle:
    CONSTITUTION_THRESHOLDS: Dict[str, Any] = yaml.safe_load(handle)
