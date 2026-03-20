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
# Authoritative symbol resolver
# =============================


def get_enabled_symbols() -> list[str]:
    """Single source of truth for enabled trading symbols.

    Handles both ``pairs.symbols`` (derived at import) and ``pairs.pairs``
    (raw YAML list).  Every call-site that needs enabled symbols MUST use
    this function — no ad-hoc CONFIG traversal.
    """
    pairs_block = CONFIG.get("pairs", {})

    # Fast path: derived list already computed at import time
    if isinstance(pairs_block.get("symbols"), list) and pairs_block["symbols"]:
        return list(pairs_block["symbols"])

    # Fallback: derive from raw pairs list
    raw_pairs = pairs_block.get("pairs", [])
    if isinstance(raw_pairs, list):
        return [
            str(p["symbol"])
            for p in raw_pairs
            if isinstance(p, dict) and p.get("enabled") and isinstance(p.get("symbol"), str)
        ]

    return []


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
