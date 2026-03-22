import shutil
import time
from pathlib import Path


class AuditLogRotator:
    def __init__(self, log_path, max_bytes=500_000_000, retention_days=90, min_free_gb=2):
        self.log_path = Path(log_path)
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self.min_free_gb = min_free_gb

    def rotate_and_prune(self):
        # Rotate if file too large
        if self.log_path.exists() and self.log_path.stat().st_size > self.max_bytes:
            ts = int(time.time())
            rotated = self.log_path.with_name(f"{self.log_path.stem}.{ts}.jsonl")
            self.log_path.rename(rotated)
            self.log_path.touch()
        # Prune old rotated logs
        now = time.time()
        for f in self.log_path.parent.glob(f"{self.log_path.stem}.*.jsonl"):
            age_days = (now - f.stat().st_mtime) / 86400
            if age_days > self.retention_days:
                f.unlink()
        # Emergency prune if disk nearly full
        usage = shutil.disk_usage(str(self.log_path.parent))
        free_gb = usage.free / 1e9
        if free_gb < self.min_free_gb:
            rotated_logs = sorted(
                self.log_path.parent.glob(f"{self.log_path.stem}.*.jsonl"), key=lambda x: x.stat().st_mtime
            )
            for f in rotated_logs:
                f.unlink()
                usage = shutil.disk_usage(str(self.log_path.parent))
                free_gb = usage.free / 1e9
                if free_gb >= self.min_free_gb:
                    break
