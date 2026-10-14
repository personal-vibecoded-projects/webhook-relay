import hashlib
import os
import secrets
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

COOKIE = "relay_session"
hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_hash_slots = threading.BoundedSemaphore(4)
_dummy_hash = hasher.hash(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class SecuritySettings:
    public_origin: str = "http://localhost:5173"
    allow_http_cookie: bool = False

    def __post_init__(self):
        parts = urlsplit(self.public_origin)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path
        ):
            raise ValueError("RELAY_PUBLIC_ORIGIN must be an origin without a path")
        if self.allow_http_cookie and parts.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("HTTP cookies are permitted only for loopback development")

    @classmethod
    def from_environment(cls):
        return cls(
            public_origin=os.environ.get(
                "RELAY_PUBLIC_ORIGIN", "http://localhost:5173"
            ),
            allow_http_cookie=os.environ.get("RELAY_ALLOW_HTTP_COOKIE") == "1",
        )


def require_origin(request: Request):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("origin") != request.app.state.security.public_origin:
            raise HTTPException(403, "Request origin is not allowed")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(value: str) -> str:
    if not _hash_slots.acquire(blocking=False):
        raise HTTPException(
            429, "Authentication is busy; try again", headers={"Retry-After": "1"}
        )
    try:
        return hasher.hash(value)
    finally:
        _hash_slots.release()


def verify_password(value: str, encoded: str | None) -> bool:
    if not _hash_slots.acquire(blocking=False):
        raise HTTPException(
            429, "Authentication is busy; try again", headers={"Retry-After": "1"}
        )
    try:
        try:
            valid = hasher.verify(encoded or _dummy_hash, value)
        except (VerificationError, InvalidHashError):
            return False
        return bool(encoded) and valid
    finally:
        _hash_slots.release()
