"""Explicit HTTPS destination and authenticated S03 request/ACK binding.

No environment discovery, implicit route registration, credential logging or retry.
Application startup must mount the returned router with a bound owner consumer.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request


@dataclass(frozen=True)
class ActivityDeliveryEndpoint:
    binding: "ActivityTransportBinding"
    consumer: object
    maximum_payload_bytes: int

    def router(self):
        return activity_consumer_router(
            binding=self.binding, consumer=self.consumer, maximum_payload_bytes=self.maximum_payload_bytes
        )


class ActivityTransportBinding:
    def __init__(self, *, destination, identity, key: bytes, maximum_skew_seconds: int):
        url = urlsplit(destination)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != "/internal/s03/activity-deliveries"
            or not identity.strip()
            or type(key) is not bytes
            or len(key) < 32
            or type(maximum_skew_seconds) is not int
            or maximum_skew_seconds <= 0
        ):
            raise ValueError("ACTIVITY_TRANSPORT_BINDING_INVALID")
        self.destination, self.identity = destination, identity
        self._key, self.maximum_skew_seconds = key, maximum_skew_seconds

    def signature(self, timestamp, payload):
        context = f"{self.identity}\n{self.destination}\n{timestamp}\n".encode()
        return hmac.new(self._key, context + payload, hashlib.sha256).hexdigest()

    def authenticate(self, *, identity, timestamp, signature, payload, now=None):
        try:
            valid = (
                identity == self.identity
                and str(int(timestamp)) == timestamp
                and abs((time.time() if now is None else now) - int(timestamp)) <= self.maximum_skew_seconds
                and hmac.compare_digest(signature, self.signature(timestamp, payload))
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("ACTIVITY_TRANSPORT_UNAUTHENTICATED")


class ActivityHTTPSender:
    def __init__(self, binding, *, timeout_seconds: float):
        if timeout_seconds <= 0:
            raise ValueError("TRANSPORT_TIMEOUT_REQUIRED")
        self.binding, self.timeout = binding, timeout_seconds

    def __call__(self, payload: bytes):
        timestamp = str(int(time.time()))
        # TLS certificate verification is mandatory; inherited proxy settings
        # and redirects cannot silently replace the bound destination.
        with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False, verify=True) as client:
            response = client.post(
                self.binding.destination,
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-S03-Identity": self.binding.identity,
                    "X-S03-Time": timestamp,
                    "X-S03-Signature": self.binding.signature(timestamp, payload),
                },
            )
            response.raise_for_status()
            body = response.json()
            return body["delivery_id"], body["payload_hash"], body["outcome"]


def activity_consumer_router(*, binding, consumer, maximum_payload_bytes: int):
    if type(maximum_payload_bytes) is not int or maximum_payload_bytes <= 0:
        raise ValueError("TRANSPORT_PAYLOAD_LIMIT_REQUIRED")
    router = APIRouter()

    @router.post("/internal/s03/activity-deliveries")
    async def receive(request: Request):
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > maximum_payload_bytes:
                raise HTTPException(413, "ACTIVITY_PAYLOAD_TOO_LARGE")
        raw = bytes(payload)
        try:
            binding.authenticate(
                identity=request.headers.get("X-S03-Identity"),
                timestamp=request.headers.get("X-S03-Time"),
                signature=request.headers.get("X-S03-Signature"),
                payload=raw,
            )
        except ValueError:
            raise HTTPException(401, "ACTIVITY_TRANSPORT_UNAUTHENTICATED") from None
        try:
            delivery_id, payload_hash, outcome = await consumer.consume(raw)
        except ValueError:
            raise HTTPException(409, "ACTIVITY_CONSUMER_REJECTED") from None
        return {"delivery_id": delivery_id, "payload_hash": payload_hash, "outcome": outcome}

    return router
