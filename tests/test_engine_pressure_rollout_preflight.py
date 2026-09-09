from __future__ import annotations

import pytest

from services.engine.runner import validate_pressure_writer_flags


def test_pressure_writer_flags_are_dark_by_default() -> None:
    validate_pressure_writer_flags({})


def test_atomic_radar_writer_requires_all_three_flags() -> None:
    validate_pressure_writer_flags(
        {
            "SIGNAL_PRESSURE_OUTBOX_ENABLED": "true",
            "SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED": "true",
            "SIGNAL_PRESSURE_RADAR_WRITE_ENABLED": "true",
        }
    )


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        (
            {"SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED": "true"},
            "SIGNAL_PRESSURE_OUTBOX_WRITE_REQUIRES_MASTER",
        ),
        (
            {"SIGNAL_PRESSURE_RADAR_WRITE_ENABLED": "true"},
            "SIGNAL_PRESSURE_RADAR_WRITE_REQUIRES_MASTER_AND_WRITE",
        ),
        (
            {
                "SIGNAL_PRESSURE_OUTBOX_ENABLED": "true",
                "SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED": "true",
                "SIGNAL_PRESSURE_RADAR_WRITE_ENABLED": "false",
            },
            "SIGNAL_PRESSURE_DIRECT_WRITER_FORBIDDEN_RADAR_REQUIRED",
        ),
    ],
)
def test_partial_or_direct_writer_activation_fails_closed(
    flags: dict[str, str],
    reason: str,
) -> None:
    with pytest.raises(RuntimeError, match=reason):
        validate_pressure_writer_flags(flags)
