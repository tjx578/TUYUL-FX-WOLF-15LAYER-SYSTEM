import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent / "snapshots"
BASE_DIR.mkdir(exist_ok=True)

def save_snapshot(pair: str, data: dict):
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = BASE_DIR / f"{pair}_{ts}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
