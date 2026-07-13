from __future__ import annotations

import logging

from config.logging_bootstrap import _RedactingFormatter, redact_sensitive_log_text


def test_redact_sensitive_log_text_masks_database_url_and_secret_assignments(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://wolf:supersecret@db.internal:5432/wolf")

    redacted = redact_sensitive_log_text(
        "migration failed DATABASE_URL=postgresql://wolf:supersecret@db.internal:5432/wolf "
        "PGPASSWORD=supersecret redis://cache:redispass@cache.internal:6379/0"
    )

    assert "supersecret" not in redacted
    assert "redispass" not in redacted
    assert "postgresql://" not in redacted
    assert "redis://" not in redacted
    assert "DATABASE_URL=$REDACTED" in redacted
    assert "PGPASSWORD=$REDACTED" in redacted


def test_stdlib_redacting_formatter_covers_exception_text():
    formatter = _RedactingFormatter("%(levelname)s %(message)s")
    record = logging.LogRecord(
        "migration",
        logging.ERROR,
        __file__,
        1,
        "migration failed: %s",
        ("postgresql://wolf:plaintext@db.internal:5432/wolf",),
        None,
    )

    rendered = formatter.format(record)

    assert "plaintext" not in rendered
    assert "$CONNECTION_URL" in rendered
