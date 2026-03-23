import logging
import threading
import time
from collections import defaultdict


class ThrottleLogFilter(logging.Filter):
    """
    Log filter to rate-limit repetitive log messages by key.
    Output at most one log per (interval) per unique message key.
    """

    def __init__(self, interval: float = 10.0):
        """
        :param interval: minimum interval in seconds per unique log message
        """
        super().__init__()
        self.interval = interval
        self._last_emit = defaultdict(float)
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Allow logging if this message hasn't been seen in the last (interval) seconds.
        Uses (pathname, lineno, msg) as log key by default (can be tuned).
        """
        log_key = (record.pathname, record.lineno, record.getMessage())
        now = time.time()
        with self._lock:
            if now - self._last_emit[log_key] > self.interval:
                self._last_emit[log_key] = now
                return True
            # Suppress duplicate log
            return False


def patch_logger_throttle(logger_name: str = "", interval: float = 10.0):
    """
    Patch global (root) logger or named logger with throttle filter.
    :param logger_name: "" for root logger, or use name ("pipeline", etc)
    :param interval: throttle interval per message (seconds)
    """
    logger = logging.getLogger(logger_name)
    throttle_filter = ThrottleLogFilter(interval=interval)
    logger.addFilter(throttle_filter)


# Example usage:
if __name__ == "__main__":
    # Patch all logs globally to only allow same line/text every 10 seconds
    patch_logger_throttle(interval=10.0)

    log = logging.getLogger("test")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    for i in range(30):
        log.warning("This will only print once every 10 seconds [loop %d]", i)
        time.sleep(1)
