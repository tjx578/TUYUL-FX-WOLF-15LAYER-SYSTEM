"""Generate a Railway-safe password verifier without exposing the password."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import secrets


def main() -> None:
    password = getpass.getpass("Dashboard owner password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 14:
        raise SystemExit("Use at least 14 characters")
    try:
        # The browser counts UTF-16 units, and the route bounds JSON bytes.
        # Reserve the worst-case escaped representation of a 254-unit username.
        units = len(password.encode("utf-16-le")) // 2
        body = json.dumps({"username": "\x01" * 254, "password": password}, ensure_ascii=False, separators=(",", ":"))
        body_bytes = len(body.encode("utf-8"))
    except UnicodeError as error:
        raise SystemExit("Password contains invalid Unicode") from error
    if units > 1024 or body_bytes > 4096:
        raise SystemExit("Password exceeds the login input limit")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    print(f"pbkdf2_sha256$600000${encode(salt)}${encode(digest)}")


if __name__ == "__main__":
    main()
