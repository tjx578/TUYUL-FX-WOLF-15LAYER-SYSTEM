from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent


def _load(path: str) -> dict[str, Any]:
    """Load a YAML config file relative to project root."""
    filepath = BASE_DIR / path
    with open(filepath, encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG: dict[str, Any] = {
    "settings": _load("config/settings.yaml"),
    "pairs": _load("config/pairs.yaml"),
    "prop_firm": _load("config/prop_firm.yaml"),
    "telegram": _load("config/telegram.yaml"),
    "finnhub": _load("config/finnhub.yaml"),
    "constitution": _load("config/constitution.yaml"),
    "risk": _load("config/risk.yaml"),
}

# Extract enabled symbols list for main.py
_pairs_data = CONFIG["pairs"].get("pairs", [])
CONFIG["pairs"]["symbols"] = [pair["symbol"] for pair in _pairs_data if pair.get("enabled", False)]


# =============================
# Convenience loaders
# =============================


def load_settings() -> dict[str, Any]:
    return CONFIG["settings"]


def load_pairs() -> list[dict[str, Any]]:
    return CONFIG["pairs"]["pairs"]


def load_prop_firm() -> dict[str, Any]:
    return CONFIG["prop_firm"]


def load_constitution() -> dict[str, Any]:
    return CONFIG["constitution"]


def load_finnhub() -> dict[str, Any]:
    return CONFIG["finnhub"]


def load_telegram() -> dict[str, Any]:
    return CONFIG["telegram"]


def load_risk() -> dict[str, Any]:
    return CONFIG["risk"]
