"""
Dashboard Authentication
READ-ONLY ACCESS
"""

import os

from fastapi import Header, HTTPException

DASHBOARD_TOKEN = os.getenv("DASHBOARD_JWT_SECRET", "CHANGE_ME")


def verify_token(authorization: str = Header(None)):
    if authorization != f"Bearer {DASHBOARD_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
# Placeholder
