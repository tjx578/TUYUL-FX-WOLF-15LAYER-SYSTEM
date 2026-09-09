"""Exact server-address binding for disposable PostgreSQL acceptance."""

from __future__ import annotations

from ipaddress import ip_address, ip_interface


def require_server_address(actual: str, expected: str = "") -> str:
    """Accept loopback by default, or the exact inspected service IP.

    PostgreSQL inet text may include a host-length prefix. Network ranges,
    unspecified addresses, DNS names and mismatching container IPs are rejected.
    This check supplements the loopback DSN and disposable-database guards.
    """
    interface = ip_interface(actual)
    if interface.network.prefixlen != interface.max_prefixlen:
        raise ValueError("PostgreSQL server identity must be a single host")
    address = interface.ip
    if address.is_unspecified or address.is_multicast:
        raise ValueError("PostgreSQL server identity is not a unicast host")
    if expected:
        if address != ip_address(expected):
            raise ValueError("PostgreSQL server differs from the inspected service IP")
    elif not address.is_loopback:
        raise ValueError("PostgreSQL server requires an explicit inspected service IP")
    return str(address)
