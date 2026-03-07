"""
Tests for router_registry — ensures all routers are importable and well-formed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.router_registry import ROUTER_ENTRIES, RouterEntry, load_routers  # noqa: E402


class TestRouterRegistry:
    def test_registry_not_empty(self) -> None:
        assert len(ROUTER_ENTRIES) > 0, "Router registry must contain entries"

    def test_all_entries_are_router_entry(self) -> None:
        for entry in ROUTER_ENTRIES:
            assert isinstance(entry, RouterEntry)

    def test_all_entries_have_description(self) -> None:
        for entry in ROUTER_ENTRIES:
            assert entry.description.strip(), f"Missing description for {entry.module}.{entry.attr}"

    def test_no_duplicate_modules(self) -> None:
        seen: set[tuple[str, str]] = set()
        for entry in ROUTER_ENTRIES:
            key = (entry.module, entry.attr)
            assert key not in seen, f"Duplicate registry entry: {entry.module}.{entry.attr}"
            seen.add(key)

    def test_load_routers_returns_correct_count(self) -> None:
        routers = load_routers()
        assert len(routers) == len(ROUTER_ENTRIES)

    def test_load_routers_returns_api_router_instances(self) -> None:
        from fastapi import APIRouter

        routers = load_routers()
        for router, desc in routers:
            assert isinstance(router, APIRouter), f"Expected APIRouter for '{desc}', got {type(router)}"
