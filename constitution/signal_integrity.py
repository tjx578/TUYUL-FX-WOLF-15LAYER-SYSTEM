"""
Signal integrity layer for Layer-12 verdicts.
Handles: unique IDs, expiry, deduplication, and versioning.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from dataclasses import dataclass


@dataclass
class SignalMetadata:
    signal_id: str
    created_at: float  # Unix epoch
    expires_at: float  # Unix epoch
    analysis_hash: str  # Hash of input data to detect duplicates
    version: str = "1.0"

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - time.time())


class SignalIntegrityGuard:
    """
    Ensures Layer-12 signals are:
    1. Uniquely identified (signal_id)
    2. Time-bounded (expiry)
    3. Not duplicated (dedup by analysis hash)
    """

    DEFAULT_EXPIRY_SECONDS = 300  # 5 minutes

    def __init__(self, expiry_seconds: float = DEFAULT_EXPIRY_SECONDS):
        self._expiry_seconds = expiry_seconds
        self._recent_hashes: dict[str, float] = {}
        self._dedup_window = expiry_seconds * 2

    def generate_signal_id(self) -> str:
        return f"SIG-{uuid.uuid4().hex[:12].upper()}-{int(time.time())}"

    def compute_analysis_hash(self, symbol: str, direction: str, entry: float, sl: float, timeframe: str) -> str:
        """Hash the core signal parameters to detect duplicates."""
        raw = f"{symbol}|{direction}|{entry:.5f}|{sl:.5f}|{timeframe}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_duplicate(self, analysis_hash: str) -> bool:
        """Check if a signal with same analysis hash was recently emitted."""
        self._cleanup_old_hashes()
        return analysis_hash in self._recent_hashes

    def register_signal(self, analysis_hash: str) -> None:
        self._recent_hashes[analysis_hash] = time.time()

    def create_metadata(
        self,
        symbol: str,
        direction: str,
        entry: float,
        sl: float,
        timeframe: str,
        expiry_override: float | None = None,
    ) -> tuple[SignalMetadata, bool]:
        """
        Create signal metadata. Returns (metadata, is_new).
        If is_new is False, this is a duplicate and should NOT be forwarded.
        """
        analysis_hash = self.compute_analysis_hash(symbol, direction, entry, sl, timeframe)

        if self.is_duplicate(analysis_hash):
            # Return metadata but flag as duplicate
            return SignalMetadata(
                signal_id="DUPLICATE",
                created_at=time.time(),
                expires_at=0,
                analysis_hash=analysis_hash,
            ), False

        expiry = expiry_override or self._expiry_seconds
        metadata = SignalMetadata(
            signal_id=self.generate_signal_id(),
            created_at=time.time(),
            expires_at=time.time() + expiry,
            analysis_hash=analysis_hash,
        )
        self.register_signal(analysis_hash)
        return metadata, True

    def validate_for_execution(self, metadata: SignalMetadata) -> tuple[bool, str]:
        """
        Final gate check before execution handoff.
        Returns (allowed, reason).
        """
        if metadata.signal_id == "DUPLICATE":
            return False, "DUPLICATE_SIGNAL"
        if metadata.is_expired:
            return False, f"SIGNAL_EXPIRED (expired {time.time() - metadata.expires_at:.1f}s ago)"
        return True, "VALID"

    def _cleanup_old_hashes(self) -> None:
        cutoff = time.time() - self._dedup_window
        self._recent_hashes = {
            h: t for h, t in self._recent_hashes.items() if t > cutoff
        }
