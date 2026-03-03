"""
Runtime schema validator for critical data contracts.
Must be called at boundaries between zones.
"""

from __future__ import annotations

import json
import logging

from pathlib import Path
from typing import Any

from schemas.signal_contract import FROZEN_SIGNAL_CONTRACT_VERSION

logger = logging.getLogger("tuyul.schemas")

try:
    import jsonschema  # pyright: ignore[reportMissingModuleSource]
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    logger.warning("jsonschema not installed -- runtime validation disabled")


_SCHEMA_CACHE: dict[str, dict] = {}
_SCHEMA_DIR = Path(__file__).parent


def _load_schema(schema_name: str) -> dict | None:
    if schema_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_name]

    filepath = _SCHEMA_DIR / schema_name
    if not filepath.exists():
        logger.error(f"Schema file not found: {filepath}")
        return None

    try:
        with open(filepath, encoding="utf-8") as f:
            schema = json.load(f)
        _SCHEMA_CACHE[schema_name] = schema
        return schema
    except Exception as e:
        logger.error(f"Failed to load schema {schema_name}: {e}")
        return None


def validate_l12_signal(signal: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate an L12 signal against the schema.
    Returns (is_valid, list_of_errors).

    MUST be called before signal crosses zone boundaries:
    - Constitution -> Dashboard
    - Dashboard -> Execution
    """
    if not HAS_JSONSCHEMA:
        logger.warning("Skipping L12 validation -- jsonschema not available")
        return True, []

    schema = _load_schema("l12_signal_schema.json")
    if schema is None:
        return False, ["Schema file not found"]

    errors: list[str] = []
    try:
        jsonschema.validate(instance=signal, schema=schema) # pyright: ignore[reportPossiblyUnboundVariable]
    except jsonschema.ValidationError as e: # pyright: ignore[reportPossiblyUnboundVariable]
        errors.append(f"Validation error: {e.message} at {list(e.absolute_path)}")
    except jsonschema.SchemaError as e: # pyright: ignore[reportPossiblyUnboundVariable]
        errors.append(f"Schema error: {e.message}")

    # Constitutional boundary check: signal must NOT contain account state
    forbidden_keys = {"balance", "equity", "account_balance", "lot_size", "risk_amount"}
    found_forbidden = forbidden_keys.intersection(signal.keys())
    if found_forbidden:
        errors.append(
            f"CONSTITUTIONAL VIOLATION: L12 signal contains account-level keys: {found_forbidden}. "
            f"Lot sizing is dashboard authority, not analysis/constitution."
        )

    if errors:
        for err in errors:
            logger.error(f"L12 signal validation: {err}")
        return False, errors

    return True, []


def validate_alert(alert: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate an alert/event against alert_schema.json."""
    if not HAS_JSONSCHEMA:
        return True, []

    schema = _load_schema("alert_schema.json")
    if schema is None:
        return False, ["Schema file not found"]

    errors: list[str] = []
    try:
        jsonschema.validate(instance=alert, schema=schema) # pyright: ignore[reportPossiblyUnboundVariable]
    except jsonschema.ValidationError as e: # pyright: ignore[reportPossiblyUnboundVariable]
        errors.append(f"Validation error: {e.message}")

    return len(errors) == 0, errors


def validate_signal_contract(signal: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate frozen dashboard SignalContract payload."""
    if not HAS_JSONSCHEMA:
        return True, []

    schema = _load_schema("signal_schema.json")
    if schema is None:
        return False, ["Schema file not found"]

    errors: list[str] = []
    try:
        jsonschema.validate(instance=signal, schema=schema)  # pyright: ignore[reportPossiblyUnboundVariable]
    except jsonschema.ValidationError as e:  # pyright: ignore[reportPossiblyUnboundVariable]
        errors.append(f"Validation error: {e.message} at {list(e.absolute_path)}")
    except jsonschema.SchemaError as e:  # pyright: ignore[reportPossiblyUnboundVariable]
        errors.append(f"Schema error: {e.message}")

    version = str(signal.get("contract_version", ""))
    if version != FROZEN_SIGNAL_CONTRACT_VERSION:
        errors.append(
            "Frozen SignalContract mismatch: "
            f"expected {FROZEN_SIGNAL_CONTRACT_VERSION}, got {version or 'missing'}"
        )

    if errors:
        for err in errors:
            logger.error(f"Signal contract validation: {err}")
        return False, errors

    return True, []
