"""
Event deduplication logic.

Same-day events from a single provider pass may still contain duplicates
due to repeated fetches or pagination overlaps.  The `deduplicate_events`
function removes duplicates using canonical_id as the stable key,
preferring higher-confidence events when the same canonical_id appears
multiple times.
"""

from __future__ import annotations

from news.models import EconomicEvent, SourceConfidence

_CONFIDENCE_ORDER = {
    SourceConfidence.HIGH: 3,
    SourceConfidence.MEDIUM: 2,
    SourceConfidence.LOW: 1,
}


def deduplicate_events(events: list[EconomicEvent]) -> list[EconomicEvent]:
    """
    Remove duplicate events by canonical_id.

    When duplicates exist, the one with the higher source_confidence is kept.
    When confidence is equal, the first occurrence (insertion order) is kept.

    Parameters
    ----------
    events : list[EconomicEvent]
        Raw event list from a single provider fetch.

    Returns
    -------
    list[EconomicEvent]
        Deduplicated list preserving relative order of the winning event.
    """
    seen: dict[str, EconomicEvent] = {}
    ordered: list[str] = []  # insertion order for canonical_ids

    for event in events:
        cid = event.canonical_id

        if not cid:
            # No canonical_id → cannot deduplicate; keep as-is with a synthetic key
            cid = event.event_id
            event.canonical_id = cid

        if cid not in seen:
            seen[cid] = event
            ordered.append(cid)
        else:
            existing = seen[cid]
            existing_score = _CONFIDENCE_ORDER.get(existing.source_confidence, 0)
            new_score = _CONFIDENCE_ORDER.get(event.source_confidence, 0)
            if new_score > existing_score:
                seen[cid] = event

    return [seen[cid] for cid in ordered]
