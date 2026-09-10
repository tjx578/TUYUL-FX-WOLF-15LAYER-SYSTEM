"""Generate a Railway-safe password verifier without exposing the password."""

from __future__ import annotations

import base64
import getpass
import hashlib
import secrets


def main() -> None:
    password = getpass.getpass("Dashboard owner password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 14:
        raise SystemExit("Use at least 14 characters")
    if len(password) > 1024 or len(password.encode("utf-8")) > 3072:
        raise SystemExit("Password exceeds the login input limit")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    print(f"pbkdf2_sha256$600000${encode(salt)}${encode(digest)}")


if __name__ == "__main__":
    main()
