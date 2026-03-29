"""
dashboard/api_key_manager.py — API Key lifecycle management.

Provides create / validate / rotate / revoke for HMAC-signed API keys.
Keys are prefixed ``wolf_`` and persisted to a JSON file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class KeyStatus(StrEnum):
    ACTIVE = "active"
    ROTATING = "rotating"
    REVOKED = "revoked"


@dataclass
class KeyRecord:
    key_id: str
    owner: str
    key_hash: str
    label: str = ""
    scopes: list[str] = field(default_factory=list)
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    rotated_from: str | None = None
    rotated_at: float | None = None


class APIKeyManager:
    """Manages wolf_ API keys with HMAC signing, rotation, and persistence."""

    _PREFIX = "wolf_"

    def __init__(self, secret_key: str, storage_path: Path | None = None, *, grace_period: float = 300.0) -> None:
        if not secret_key:
            raise ValueError("API_KEY_SECRET must not be empty")
        self._secret = secret_key.encode("utf-8")
        self._storage = storage_path
        self._grace_period = grace_period
        self._keys: dict[str, KeyRecord] = {}
        if self._storage and self._storage.exists():
            self._load()

    # ── public API ────────────────────────────────────────────────

    def create_key(
        self,
        owner: str,
        label: str = "",
        scopes: list[str] | None = None,
    ) -> dict[str, str]:
        key_id = secrets.token_hex(8)
        raw_key = f"{self._PREFIX}{secrets.token_hex(24)}"
        key_hash = self._hash(raw_key)

        record = KeyRecord(
            key_id=key_id,
            owner=owner,
            key_hash=key_hash,
            label=label,
            scopes=scopes or [],
        )
        self._keys[key_id] = record
        self._persist()
        return {"raw_key": raw_key, "key_id": key_id}

    def validate_key(self, raw_key: str) -> KeyRecord | None:
        h = self._hash(raw_key)
        for rec in self._keys.values():
            if hmac.compare_digest(rec.key_hash, h):
                if rec.status == KeyStatus.REVOKED:
                    return None
                if rec.status == KeyStatus.ROTATING:
                    if rec.rotated_at is None:
                        return None
                    if time.time() - rec.rotated_at > self._grace_period:
                        return None
                return rec
        return None

    def rotate_key(self, old_key_id: str) -> dict[str, str] | None:
        old = self._keys.get(old_key_id)
        if old is None:
            return None
        old.status = KeyStatus.ROTATING
        old.rotated_at = time.time()

        new_key_id = secrets.token_hex(8)
        raw_key = f"{self._PREFIX}{secrets.token_hex(24)}"
        new_rec = KeyRecord(
            key_id=new_key_id,
            owner=old.owner,
            key_hash=self._hash(raw_key),
            label=old.label,
            scopes=list(old.scopes),
            rotated_from=old_key_id,
        )
        self._keys[new_key_id] = new_rec
        self._persist()
        return {"raw_key": raw_key, "key_id": new_key_id}

    def revoke_key(self, key_id: str) -> None:
        rec = self._keys.get(key_id)
        if rec:
            rec.status = KeyStatus.REVOKED
            self._persist()

    def list_keys(self, owner: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self._keys.values():
            if owner and rec.owner != owner:
                continue
            d = asdict(rec)
            d.pop("key_hash", None)
            out.append(d)
        return out

    # ── internal ──────────────────────────────────────────────────

    def _hash(self, raw_key: str) -> str:
        return hmac.new(self._secret, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()

    def _persist(self) -> None:
        if not self._storage:
            return
        data = {kid: asdict(rec) for kid, rec in self._keys.items()}
        tmp = self._storage.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self._storage)

    def _load(self) -> None:
        if not self._storage or not self._storage.exists():
            return
        raw = json.loads(self._storage.read_text())
        for kid, d in raw.items():
            d["status"] = KeyStatus(d["status"])
            self._keys[kid] = KeyRecord(**d)
