"""
API Key rotation and management.

Zone: dashboard (security infrastructure).

Features:
- Generate API keys with configurable expiry.
- Grace-period rotation (old + new key both valid during overlap).
- Keys stored as SHA-256 hashes (never raw).
- Automatic cleanup of expired keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any  # noqa: UP035

logger = logging.getLogger(__name__)

API_KEY_LENGTH = 48          # bytes
DEFAULT_MAX_AGE = 86400 * 90  # 90 days
ROTATION_GRACE_PERIOD = 86400 * 7  # 7 days — old key still valid


class KeyStatus(Enum):
    ACTIVE = "active"
    ROTATING = "rotating"      # Grace period — being replaced
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class APIKeyRecord:
    """Stored record for an API key (hash only, never raw key)."""
    key_id: str
    key_hash: str
    owner: str
    label: str
    status: KeyStatus
    created_at: float
    expires_at: float
    rotated_at: float | None = None
    revoked_at: float | None = None
    scopes: list[str] = field(default_factory=lambda: ["read"])

    def is_valid(self, now: float | None = None) -> bool:
        now = now or time.time()
        if self.status == KeyStatus.REVOKED:
            return False
        if self.status == KeyStatus.EXPIRED:
            return False
        if now > self.expires_at:
            return False
        if self.status == KeyStatus.ROTATING and self.rotated_at:
            # Valid during grace period after rotation
            grace_end = self.rotated_at + ROTATION_GRACE_PERIOD
            if now > grace_end:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "key_hash": self.key_hash,
            "owner": self.owner,
            "label": self.label,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "rotated_at": self.rotated_at,
            "revoked_at": self.revoked_at,
            "scopes": self.scopes,
        }

    @staticmethod
    def from_dict(d: dict) -> APIKeyRecord:
        return APIKeyRecord(
            key_id=d["key_id"],
            key_hash=d["key_hash"],
            owner=d["owner"],
            label=d["label"],
            status=KeyStatus(d["status"]),
            created_at=d["created_at"],
            expires_at=d["expires_at"],
            rotated_at=d.get("rotated_at"),
            revoked_at=d.get("revoked_at"),
            scopes=d.get("scopes", ["read"]),
        )


class APIKeyManager:
    """
    Manages API key lifecycle: creation, validation, rotation, revocation.

    Keys are stored as SHA-256 hashes. The raw key is returned exactly once
    upon creation and never stored.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        storage_path: Path | None = None,
    ) -> None:
        self._secret = (secret_key or os.environ.get("API_KEY_SECRET", "")).encode()
        if not self._secret:
            raise ValueError("API_KEY_SECRET must be set.")
        self._storage_path = storage_path
        self._keys: dict[str, APIKeyRecord] = {}  # key_id → record
        self._hash_index: dict[str, str] = {}      # key_hash → key_id

        if self._storage_path and self._storage_path.exists():
            self._load()

    # ── Key Lifecycle ────────────────────────────────────────────────

    def create_key(
        self,
        owner: str,
        label: str = "default",
        scopes: list[str] | None = None,
        max_age: int = DEFAULT_MAX_AGE,
    ) -> dict[str, Any]:
        """
        Create a new API key.

        Returns dict with 'raw_key', 'key_id', 'expires_at'.
        The raw_key is returned ONCE — store it securely!
        """
        raw_key = f"wolf_{secrets.token_urlsafe(API_KEY_LENGTH)}"
        key_hash = self._hash_key(raw_key)
        key_id = f"kid_{secrets.token_urlsafe(12)}"
        now = time.time()

        record = APIKeyRecord(
            key_id=key_id,
            key_hash=key_hash,
            owner=owner,
            label=label,
            status=KeyStatus.ACTIVE,
            created_at=now,
            expires_at=now + max_age,
            scopes=scopes or ["read"],
        )

        self._keys[key_id] = record
        self._hash_index[key_hash] = key_id
        self._save()

        logger.info(
            "API key created: key_id=%s owner=%s label=%s expires_in=%dd",
            key_id, owner, label, max_age // 86400,
        )

        return {
            "raw_key": raw_key,
            "key_id": key_id,
            "expires_at": record.expires_at,
            "scopes": record.scopes,
        }

    def validate_key(self, raw_key: str) -> APIKeyRecord | None:
        """
        Validate a raw API key. Returns the record if valid, None if invalid.

        Does NOT log the raw key.
        """
        key_hash = self._hash_key(raw_key)
        key_id = self._hash_index.get(key_hash)

        if key_id is None:
            logger.warning("API key validation failed: unknown key hash")
            return None

        record = self._keys.get(key_id)
        if record is None or not record.is_valid():
            logger.warning(
                "API key validation failed: key_id=%s status=%s",
                key_id, record.status.value if record else "missing",
            )
            return None

        return record

    def rotate_key(self, key_id: str) -> dict[str, Any] | None:
        """
        Rotate an existing key.

        - Old key enters ROTATING state (valid for grace period).
        - New key is created with same owner/label/scopes.
        - Returns new key info, or None if key_id not found.
        """
        old_record = self._keys.get(key_id)
        if old_record is None:
            logger.warning("Rotation failed: key_id=%s not found", key_id)
            return None

        if old_record.status not in (KeyStatus.ACTIVE, KeyStatus.ROTATING):
            logger.warning("Rotation failed: key_id=%s status=%s", key_id, old_record.status.value)
            return None

        # Mark old key as rotating
        old_record.status = KeyStatus.ROTATING
        old_record.rotated_at = time.time()

        # Create new key with same properties
        new_key_info = self.create_key(
            owner=old_record.owner,
            label=old_record.label,
            scopes=old_record.scopes,
            max_age=int(old_record.expires_at - old_record.created_at),  # Same lifetime
        )

        logger.info(
            "API key rotated: old=%s → new=%s grace_period=%dd",
            key_id, new_key_info["key_id"], ROTATION_GRACE_PERIOD // 86400,
        )

        self._save()
        return new_key_info

    def revoke_key(self, key_id: str) -> bool:
        """Immediately revoke a key. Returns True if found."""
        record = self._keys.get(key_id)
        if record is None:
            return False
        record.status = KeyStatus.REVOKED
        record.revoked_at = time.time()
        self._save()
        logger.info("API key revoked: key_id=%s owner=%s", key_id, record.owner)
        return True

    def cleanup_expired(self) -> int:
        """Remove expired and finished-rotating keys. Returns count removed."""
        now = time.time()
        to_remove = []
        for key_id, record in self._keys.items():
            if record.status == KeyStatus.REVOKED or now > record.expires_at or (record.status == KeyStatus.ROTATING
                  and record.rotated_at
                  and now > record.rotated_at + ROTATION_GRACE_PERIOD):
                to_remove.append(key_id)

        for key_id in to_remove:
            record = self._keys.pop(key_id, None)
            if record:
                self._hash_index.pop(record.key_hash, None)

        if to_remove:
            self._save()
            logger.info("Cleaned up %d expired/revoked API keys", len(to_remove))
        return len(to_remove)

    def list_keys(self, owner: str | None = None) -> list[dict[str, Any]]:
        """List key records (without hashes). Optionally filter by owner."""
        results = []
        for record in self._keys.values():
            if owner and record.owner != owner:
                continue
            info = record.to_dict()
            del info["key_hash"]  # Never expose hash
            results.append(info)
        return results

    # ── Internal ─────────────────────────────────────────────────────

    def _hash_key(self, raw_key: str) -> str:
        return hmac.new(self._secret, raw_key.encode(), hashlib.sha256).hexdigest()

    def _save(self) -> None:
        if not self._storage_path:
            return
        data = [r.to_dict() for r in self._keys.values()]
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._storage_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(self._storage_path)

    def _load(self) -> None:
        if not self._storage_path or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text())
            for d in data:
                record = APIKeyRecord.from_dict(d)
                self._keys[record.key_id] = record
                self._hash_index[record.key_hash] = record.key_id
            logger.info("Loaded %d API keys from %s", len(self._keys), self._storage_path)
        except Exception as e:
            logger.error("Failed to load API keys: %s", e)
