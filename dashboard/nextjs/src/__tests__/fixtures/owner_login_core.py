"""Disposable loopback authority for the frontend contract test; no app startup."""

import base64
import hashlib
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402

from api.auth_router import router  # noqa: E402
from api.middleware import auth  # noqa: E402
from api.middleware.rbac import Permission, require_permission  # noqa: E402


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


salt = b"disposable-salt16"
digest = hashlib.pbkdf2_hmac("sha256", b"disposable-test-password", salt, 210000)
os.environ["DASHBOARD_OWNER_USERNAME"] = "owner@example.test"
os.environ["DASHBOARD_OWNER_PASSWORD_HASH"] = f"pbkdf2_sha256$210000${encode(salt)}${encode(digest)}"
auth.JWT_SECRET = "disposable-contract-secret-at-least-32-characters"
auth.JWT_VERIFY_SECRETS = (auth.JWT_SECRET,)
auth.API_KEY = ""
app = FastAPI()
app.include_router(router)


@app.get("/ready")
def ready():
    return {"ready": True}


@app.post("/privileged", dependencies=[Depends(require_permission(Permission.RISK_KILL_SWITCH))])
def privileged():
    raise AssertionError("Viewer must never reach privileged handler")


@app.get("/expired-fixture")
def expired_fixture():
    return {
        "token": auth.create_token(
            "owner@example.test",
            {"role": "viewer", "scopes": ["read:dashboard"], "exp": int(time.time()) - 30},
        )
    }


sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(f"CONTRACT_PORT={sock.getsockname()[1]}", flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False)).run(sockets=[sock])
