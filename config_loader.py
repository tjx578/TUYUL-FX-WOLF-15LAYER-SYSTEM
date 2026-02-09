import functools
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    with path.open() as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=None)
def load_settings() -> dict:
    return _load_yaml("settings.yaml")


@functools.lru_cache(maxsize=None)
def load_pairs() -> list:
    data = _load_yaml("pairs.yaml")
    return data.get("pairs", []) if data else []


@functools.lru_cache(maxsize=None)
def load_constitution() -> dict:
    return _load_yaml("constitution.yaml")


@functools.lru_cache(maxsize=None)
def load_prop_firm() -> dict:
    return _load_yaml("prop_firm.yaml")


@functools.lru_cache(maxsize=None)
def load_twelve_data() -> dict:
    return _load_yaml("twelve_data.yaml")
