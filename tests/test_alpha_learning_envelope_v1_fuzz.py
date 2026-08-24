"""Deterministic fail-closed fuzz gates for the WLA-01 contract boundary."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from pathlib import Path

import pytest

from contracts.alpha_learning_envelope_v1 import (
    MAX_CANONICAL_ENVELOPE_BYTES,
    ProducerAuthenticationError,
    authenticate_alpha_learning_envelope_v1,
    parse_alpha_learning_envelope_v1,
)
from tests.wla01_contract.fixture_factory import FIXTURE_ROOT, producer_key_registry

FUZZ_SEED = 0x20260824
MUTATION_CASES = 4096
ARBITRARY_BYTE_CASES = 1024


def _baseline_bytes() -> bytes:
    path = FIXTURE_ROOT / "positive" / "alpha_decision.canonical.json"
    stored = Path(path).read_bytes()
    assert stored.endswith(b"\n")
    return stored[:-1]


def _mutate(raw: bytes, *, index: int, rng: random.Random) -> tuple[str, bytes]:
    mode = ("flip", "delete", "insert", "replace")[index % 4]
    data = bytearray(raw)

    if mode == "flip":
        position = rng.randrange(len(data))
        data[position] ^= rng.randrange(1, 256)
    elif mode == "delete":
        width = rng.randint(1, min(8, len(data) - 1))
        start = rng.randrange(0, len(data) - width + 1)
        del data[start : start + width]
    elif mode == "insert":
        width = rng.randint(1, 8)
        start = rng.randrange(0, len(data) + 1)
        data[start:start] = bytes(rng.randrange(256) for _ in range(width))
    else:
        width = rng.randint(1, min(8, len(data)))
        start = rng.randrange(0, len(data) - width + 1)
        replacement = bytearray(rng.randrange(256) for _ in range(width))
        replacement[0] = data[start] ^ rng.randrange(1, 256)
        data[start : start + width] = replacement

    mutated = bytes(data)
    assert mutated != raw
    return mode, mutated


def _classify_changed_bytes(raw: bytes) -> str:
    try:
        untrusted = parse_alpha_learning_envelope_v1(raw)
    except ValueError:
        return "STRUCTURAL_REJECT"

    assert untrusted.trust_status == "UNTRUSTED"
    try:
        authenticate_alpha_learning_envelope_v1(
            untrusted,
            key_registry=producer_key_registry(),
            known_event_hashes={},
        )
    except ProducerAuthenticationError:
        return "AUTHENTICATION_REJECT"
    pytest.fail("changed or arbitrary bytes reached ACCEPTED")


def run_deterministic_mutation_fuzz() -> tuple[dict[str, int], str]:
    """Return deterministic mutation outcomes and their stable evidence digest."""

    baseline = _baseline_bytes()
    rng = random.Random(FUZZ_SEED)
    outcomes: Counter[str] = Counter()
    evidence = hashlib.sha256()

    for index in range(MUTATION_CASES):
        mode, mutated = _mutate(baseline, index=index, rng=rng)
        outcome = _classify_changed_bytes(mutated)
        outcomes[outcome] += 1
        evidence.update(f"{index}:{mode}:{outcome}\n".encode("ascii"))

    return dict(sorted(outcomes.items())), evidence.hexdigest()


def run_deterministic_arbitrary_byte_fuzz() -> tuple[dict[str, int], str]:
    """Exercise strict parsing across deterministic arbitrary byte strings."""

    rng = random.Random(FUZZ_SEED ^ 0xA11CE)
    boundaries = (
        0,
        1,
        2,
        31,
        32,
        63,
        64,
        255,
        1024,
        MAX_CANONICAL_ENVELOPE_BYTES,
        MAX_CANONICAL_ENVELOPE_BYTES + 1,
    )
    outcomes: Counter[str] = Counter()
    evidence = hashlib.sha256()

    for index in range(ARBITRARY_BYTE_CASES):
        size = boundaries[index] if index < len(boundaries) else rng.randrange(0, 2049)
        raw = bytes(rng.randrange(256) for _ in range(size))
        outcome = _classify_changed_bytes(raw)
        outcomes[outcome] += 1
        evidence.update(f"{index}:{size}:{outcome}\n".encode("ascii"))

    return dict(sorted(outcomes.items())), evidence.hexdigest()


def test_deterministic_mutation_fuzz_is_fail_closed_and_reproducible() -> None:
    first = run_deterministic_mutation_fuzz()
    second = run_deterministic_mutation_fuzz()

    assert first == second
    assert sum(first[0].values()) == MUTATION_CASES
    assert set(first[0]).issubset({"STRUCTURAL_REJECT", "AUTHENTICATION_REJECT"})


def test_deterministic_arbitrary_byte_fuzz_is_fail_closed_and_reproducible() -> None:
    first = run_deterministic_arbitrary_byte_fuzz()
    second = run_deterministic_arbitrary_byte_fuzz()

    assert first == second
    assert sum(first[0].values()) == ARBITRARY_BYTE_CASES
    assert set(first[0]).issubset({"STRUCTURAL_REJECT", "AUTHENTICATION_REJECT"})
