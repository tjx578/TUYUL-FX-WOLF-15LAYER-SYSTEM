from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECT_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


def _direct_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = DIRECT_PIN.fullmatch(raw_line.strip())
        if match is not None:
            pins[match.group(1).casefold()] = match.group(2)
    return pins


def test_g3_profile_matches_native_mcp_import_time_dependencies() -> None:
    isolated_runtime = _direct_pins(ROOT / "ops" / "mt5_mcp" / "requirements.txt")
    g3_profile = _direct_pins(ROOT / "requirements-g3.in")

    assert isolated_runtime["mcp"] == "2.0.0"
    assert isolated_runtime["psutil"] == "7.2.2"
    assert g3_profile["mcp"] == isolated_runtime["mcp"]
    assert g3_profile["psutil"] == isolated_runtime["psutil"]
    assert "metatrader5" not in g3_profile
