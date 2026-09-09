"""Database ownership and failure restoration for the domain CI launcher."""

import psycopg
import pytest

from scripts.ci.run_strategy_persistence_acceptance import isolated_domain_database


@pytest.fixture
def guarded(monkeypatch):
    values = {
        "WOLF15_RUN_POSTGRES_INTEGRATION": "1",
        "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS": "YES_I_UNDERSTAND",
        "WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL": "postgresql://fixture@127.0.0.1/wolf15_ci_test",
        "WOLF15_POSTGRES_TEST_DATABASE": "wolf15_ci_test",
        "WOLF15_POSTGRES_TEST_SERVER_ADDRESS": "",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.mark.parametrize("marker", ["PRODUCTION", "DISPOSABLE_TEST"])
def test_child_scope_is_guarded_and_environment_restored_on_test_failure(guarded, monkeypatch, marker):
    import os

    connections = []
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query):
            statements.append(query)
            return self

        def fetchone(self):
            return "wolf15_ci_test", "127.0.0.1/32", marker, "true"

    def connect(dsn, **_):
        connections.append(dsn)
        return Connection()

    monkeypatch.setattr(psycopg, "connect", connect)
    if marker == "PRODUCTION":
        with pytest.raises(ValueError, match="TEMPLATE_IDENTITY"), isolated_domain_database():
            pytest.fail("untrusted template entered")
        assert len(connections) == len(statements) == 1
    else:
        with pytest.raises(RuntimeError, match="test failed"), isolated_domain_database() as name:
            assert name.startswith("wolf15_ci_test_domain_")
            assert os.environ["WOLF15_POSTGRES_TEST_DATABASE"] == name
            assert os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"].endswith("/" + name)
            raise RuntimeError("test failed")
        assert connections[1].endswith("/postgres")
        assert len(statements) == 4  # identity, create child, two disposable markers
    for key, value in guarded.items():
        assert os.environ[key] == value


@pytest.mark.parametrize("value", ["", "0"])
def test_disabled_domain_scope_never_connects(guarded, monkeypatch, value):
    monkeypatch.setenv("WOLF15_RUN_POSTGRES_INTEGRATION", value)
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_kw: pytest.fail("unexpected connection"))
    with pytest.raises(ValueError, match="DISPOSABLE_INTEGRATION_REQUIRED"), isolated_domain_database():
        pytest.fail("disabled test entered")
