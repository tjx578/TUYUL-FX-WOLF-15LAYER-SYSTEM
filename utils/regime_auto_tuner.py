import json
import threading
import time
from pathlib import Path

import numpy as np

THRESHOLDS_PATH = Path(__file__).parent.parent / "config" / "thresholds.py"

class RegimeAutoTuner:
    def __init__(self, window_size=500, update_interval=3600):
        self.window_size = window_size
        self.update_interval = update_interval
        self.vr_values = []
        self.lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._running = False

    def add_vr(self, vr: float):
        with self.lock:
            self.vr_values.append(vr)
            if len(self.vr_values) > self.window_size:
                self.vr_values = self.vr_values[-self.window_size:]

    def start(self):
        if not self._running:
            self._running = True
            self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            time.sleep(self.update_interval)
            self.tune_and_update()

    def tune_and_update(self):
        with self.lock:
            if len(self.vr_values) < 30:
                return  # Not enough data
            arr = np.array(self.vr_values)
            sigma = float(np.std(arr))
            k = float(np.mean(arr))
            clamp = float(np.percentile(arr, 95))
            # Update the thresholds table in-place (for demo, just print)
            # In production, write to config/thresholds.py or a JSON file
            self._write_thresholds(sigma, k, clamp)

    def _write_thresholds(self, sigma, k, clamp):
        # For safety, write to a JSON file (not overwrite .py directly)
        out_path = Path(THRESHOLDS_PATH).with_suffix('.auto.json')
        data = {
            "sigma_VR": sigma,
            "k": k,
            "clamp": clamp,
            "timestamp": time.time(),
        }
        with open(out_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[RegimeAutoTuner] Updated: {data}")
