import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def _load(path: str):
    with open(BASE_DIR / path, "r") as f:
        return yaml.safe_load(f)

CONFIG = {
    "settings": _load("config/settings.yaml"),
    "pairs": _load("config/pairs.yaml"),
    "prop_firm": _load("config/prop_firm.yaml"),
    "telegram": _load("config/telegram.yaml"),
    "twelve_data": _load("config/twelve_data.yaml"),
    "constitution": _load("config/constitution.yaml"),
}
