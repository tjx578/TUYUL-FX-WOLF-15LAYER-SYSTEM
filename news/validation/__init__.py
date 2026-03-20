"""
News validation sub-package.

Provides schema validation for scraped data and failure rate monitoring
for provider reliability tracking.
"""

from news.validation.parse_health_tracker import ParseHealthTracker
from news.validation.schema_validator import (
    ValidationResult,
    validate_ff_event,
    validate_ff_events,
)

__all__ = [
    "ParseHealthTracker",
    "ValidationResult",
    "validate_ff_event",
    "validate_ff_events",
]
