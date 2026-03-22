"""Tests for infrastructure/redis_ha.py — host parsing, HA mode detection."""

from __future__ import annotations

import os
from unittest.mock import patch

from infrastructure.redis_ha import (
    ClusterClientManager,
    SentinelClientManager,
    _parse_host_list,
    get_ha_mode,
)

# ═══════════════════════════════════════════════════════════════════════════
#  _parse_host_list
# ═══════════════════════════════════════════════════════════════════════════


class TestParseHostList:
    def test_single_host(self):
        assert _parse_host_list("host1:6379") == [("host1", 6379)]

    def test_multiple_hosts(self):
        assert _parse_host_list("h1:6379,h2:26379,h3:6380") == [
            ("h1", 6379),
            ("h2", 26379),
            ("h3", 6380),
        ]

    def test_no_port_defaults_to_6379(self):
        assert _parse_host_list("myhost") == [("myhost", 6379)]

    def test_empty_string(self):
        assert _parse_host_list("") == []

    def test_whitespace_trimmed(self):
        assert _parse_host_list("  h1:6379 , h2:6380 ") == [("h1", 6379), ("h2", 6380)]

    def test_trailing_comma_ignored(self):
        assert _parse_host_list("h1:6379,") == [("h1", 6379)]


# ═══════════════════════════════════════════════════════════════════════════
#  get_ha_mode
# ═══════════════════════════════════════════════════════════════════════════


class TestGetHaMode:
    def test_standalone_default(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove sentinel/cluster vars if they exist
            os.environ.pop("REDIS_SENTINEL_HOSTS", None)
            os.environ.pop("REDIS_CLUSTER_HOSTS", None)
            assert get_ha_mode() == "standalone"

    def test_sentinel_priority(self):
        with patch.dict(
            os.environ,
            {
                "REDIS_SENTINEL_HOSTS": "h1:26379",
                "REDIS_CLUSTER_HOSTS": "h2:6380",
            },
        ):
            assert get_ha_mode() == "sentinel"

    def test_cluster_when_no_sentinel(self):
        env = {"REDIS_CLUSTER_HOSTS": "h1:6379,h2:6379"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_SENTINEL_HOSTS", None)
            assert get_ha_mode() == "cluster"


# ═══════════════════════════════════════════════════════════════════════════
#  SentinelClientManager config
# ═══════════════════════════════════════════════════════════════════════════


class TestSentinelClientManagerConfig:
    def test_config_parsing(self):
        env = {
            "REDIS_SENTINEL_HOSTS": "s1:26379,s2:26379,s3:26379",
            "REDIS_SENTINEL_MASTER": "wolf-master",
            "REDIS_SENTINEL_PASSWORD": "secret",
            "REDIS_SENTINEL_DB": "2",
        }
        with patch.dict(os.environ, env, clear=False):
            mgr = SentinelClientManager()
            hosts, master, password, db = mgr._get_config()
            assert len(hosts) == 3
            assert master == "wolf-master"
            assert password == "secret"
            assert db == 2

    def test_defaults(self):
        env = {"REDIS_SENTINEL_HOSTS": "s1:26379"}
        with patch.dict(os.environ, env, clear=False):
            for key in ("REDIS_SENTINEL_MASTER", "REDIS_SENTINEL_PASSWORD", "REDIS_SENTINEL_DB", "REDIS_PASSWORD"):
                os.environ.pop(key, None)
            mgr = SentinelClientManager()
            hosts, master, password, db = mgr._get_config()
            assert master == "mymaster"
            assert password is None
            assert db == 0

    def test_falls_back_to_redis_password(self):
        env = {
            "REDIS_SENTINEL_HOSTS": "s1:26379",
            "REDIS_PASSWORD": "fallback",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REDIS_SENTINEL_PASSWORD", None)
            mgr = SentinelClientManager()
            _, _, password, _ = mgr._get_config()
            assert password == "fallback"


# ═══════════════════════════════════════════════════════════════════════════
#  ClusterClientManager
# ═══════════════════════════════════════════════════════════════════════════


class TestClusterClientManager:
    def test_init_no_connection(self):
        mgr = ClusterClientManager()
        assert mgr._client is None
