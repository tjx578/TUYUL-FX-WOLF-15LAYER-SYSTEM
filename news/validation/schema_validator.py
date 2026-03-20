"""
Schema validator for scraped / fetched news data.

Validates raw event dicts from ForexFactory and Finnhub before they
enter the normalization pipeline. Catches format changes early.

Zone: analysis/ -- pure validation, no execution side-effects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a single raw event dict."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── ForexFactory JSON Schema Rules ────────────────────────────────────────────

# Required fields from the FF JSON endpoint
_FF_REQUIRED_FIELDS: set[str] = {"title", "country", "date", "impact"}
_FF_ALTERNATE_TITLE_FIELDS: list[str] = ["name", "event"]
_FF_VALID_IMPACTS: set[str] = {"high", "medium", "med", "low", "holiday", "non-economic"}
_FF_VALID_CURRENCIES: set[str] = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "AUD",
    "NZD",
    "CAD",
    "CNY",
    "SEK",
    "NOK",
    "DKK",
    "SGD",
    "HKD",
    "MXN",
    "ZAR",
    "TRY",
    "PLN",
    "CZK",
    "HUF",
    "ALL",
}
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")


def validate_ff_event(raw: dict[str, Any]) -> ValidationResult:
    """
    Validate a single ForexFactory raw event dict.

    Checks:
    1. Required fields present (title/name/event, country/currency, date, impact)
    2. Impact value is a recognized string
    3. Currency/country is a valid code
    4. Date field is parseable (ISO or FF format)
    5. Numeric fields (actual, forecast, previous) are string or None

    Returns
    -------
    ValidationResult
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Title field (one of title/name/event must exist)
    title = raw.get("title") or raw.get("name") or raw.get("event")
    if not title or not str(title).strip():
        errors.append("missing_title: no 'title', 'name', or 'event' field")

    # 2. Currency / country field
    currency = raw.get("currency") or raw.get("country")
    if not currency:
        errors.append("missing_currency: no 'currency' or 'country' field")
    elif str(currency).strip().upper() not in _FF_VALID_CURRENCIES:
        warnings.append(f"unknown_currency: '{currency}' not in recognized set")

    # 3. Date field
    date_val = raw.get("date")
    if not date_val:
        errors.append("missing_date: no 'date' field")
    else:
        date_str = str(date_val).strip()
        if not _ISO_DATE_PATTERN.match(date_str):  # noqa: SIM102
            # Check for other parseable formats
            if "T" not in date_str:
                errors.append(f"invalid_date_format: '{date_str}' not ISO-like")

    # 4. Impact field
    impact = raw.get("impact")
    if not impact:
        warnings.append("missing_impact: no 'impact' field (will default to UNKNOWN)")
    elif str(impact).strip().lower() not in _FF_VALID_IMPACTS:
        warnings.append(f"unknown_impact: '{impact}' not in recognized set")

    # 5. Value fields should be string or None
    for val_field in ("actual", "forecast", "previous", "estimate", "prev"):
        val = raw.get(val_field)
        if val is not None and not isinstance(val, str):
            warnings.append(f"non_string_value: '{val_field}' is {type(val).__name__}, expected str")

    # 6. Check for unexpected structure changes (new/removed fields)
    known_fields = {
        "title",
        "name",
        "event",
        "currency",
        "country",
        "date",
        "time",
        "impact",
        "actual",
        "forecast",
        "estimate",
        "previous",
        "prev",
        "url",
        "betterThan",
        "better_than",
    }
    unknown_fields = set(raw.keys()) - known_fields
    if unknown_fields:
        warnings.append(f"unknown_fields: {sorted(unknown_fields)}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def validate_ff_events(
    raw_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[ValidationResult]]:
    """
    Validate a batch of FF raw events.

    Returns
    -------
    tuple of (valid_events, invalid_events, all_results)
    """
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    results: list[ValidationResult] = []

    for raw in raw_events:
        result = validate_ff_event(raw)
        results.append(result)
        if result.valid:
            valid.append(raw)
        else:
            invalid.append(raw)
            logger.warning(
                "FF event validation failed: errors=%s raw=%s",
                result.errors,
                {k: raw.get(k) for k in ("title", "date", "currency", "impact")},
            )

    if invalid:
        total = len(raw_events)
        logger.warning(
            "FF validation: %d/%d events invalid (%.1f%%)",
            len(invalid),
            total,
            (len(invalid) / total * 100) if total else 0,
        )

    return valid, invalid, results


# ── Finnhub Schema Validation ────────────────────────────────────────────────

_FINNHUB_REQUIRED_FIELDS: set[str] = {"event", "country"}


def validate_finnhub_event(raw: dict[str, Any]) -> ValidationResult:
    """
    Validate a single Finnhub raw event dict.
    """
    errors: list[str] = []
    warnings: list[str] = []

    event = raw.get("event") or raw.get("name")
    if not event or not str(event).strip():
        errors.append("missing_event: no 'event' or 'name' field")

    currency = raw.get("currency")
    if not currency:
        warnings.append("missing_currency: no 'currency' field")

    # Finnhub uses unix timestamps or ISO strings
    for ts_field in ("timestamp", "date"):
        val = raw.get(ts_field)
        if val is not None and not isinstance(val, (int, float, str)):
            errors.append(f"invalid_{ts_field}: type {type(val).__name__}")

    impact = raw.get("impact")
    if impact is not None and not isinstance(impact, (int, str)):
        warnings.append(f"unexpected_impact_type: {type(impact).__name__}")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
