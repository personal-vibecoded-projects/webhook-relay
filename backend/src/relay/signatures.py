"""Versioned HMAC signatures with explicit rotation and bounded parsing."""

import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field

MAX_PAYLOAD_BYTES = 256 * 1024
MAX_HEADER_BYTES = 2048
MAX_KEYS = 8
_KEY_ID = re.compile(r"[a-zA-Z0-9_-]{1,32}\Z")
_TIMESTAMP = re.compile(r"(?:0|[1-9][0-9]{0,11})\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class InvalidSignature(ValueError):
    """Authentication failed; deliberately omits header, body, and key data."""


@dataclass(frozen=True)
class SigningKey:
    key_id: str
    secret: bytes = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.key_id, str) or not _KEY_ID.fullmatch(self.key_id):
            raise ValueError("Invalid signing key identifier")
        if not isinstance(self.secret, bytes) or not 32 <= len(self.secret) <= 128:
            raise ValueError("Signing keys must contain 32 to 128 bytes")


@dataclass(frozen=True)
class VerifiedSignature:
    key_id: str
    timestamp: int


def _keys(keys: tuple[SigningKey, ...]) -> None:
    if not 1 <= len(keys) <= MAX_KEYS:
        raise ValueError("Expected one to eight signing keys")
    if any(not isinstance(key, SigningKey) for key in keys):
        raise ValueError("Invalid signing key")
    if len({key.key_id for key in keys}) != len(keys):
        raise ValueError("Signing key identifiers must be unique")


def _timestamp(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 999_999_999_999:
        raise ValueError("Invalid timestamp")


def _mac(body: bytes, timestamp: int, key: SigningKey) -> str:
    prefix = f"v1.{timestamp}.{key.key_id}.".encode("ascii")
    digest = hmac.new(key.secret, prefix, hashlib.sha256)
    digest.update(body)
    return digest.hexdigest()


def sign_payload(
    body: bytes, keys: tuple[SigningKey, ...], *, timestamp: int | None = None
) -> str:
    """Sign exact wire bytes; multiple active keys support overlap during rotation."""
    _keys(keys)
    if not isinstance(body, bytes) or len(body) > MAX_PAYLOAD_BYTES:
        raise ValueError("Invalid payload size or type")
    timestamp = int(time.time()) if timestamp is None else timestamp
    _timestamp(timestamp)
    entries = [f"v1={key.key_id}:{_mac(body, timestamp, key)}" for key in keys]
    return ",".join([f"t={timestamp}", *entries])


def _parse_header(header: str) -> tuple[int, list[tuple[str, str]]]:
    if not isinstance(header, str) or len(header) > MAX_HEADER_BYTES:
        raise InvalidSignature("Invalid webhook signature")
    # ASCII length equals byte length and excludes invisible Unicode separators.
    if not header.isascii():
        raise InvalidSignature("Invalid webhook signature")
    parts = header.split(",")
    if not 2 <= len(parts) <= MAX_KEYS + 1 or not parts[0].startswith("t="):
        raise InvalidSignature("Invalid webhook signature")
    raw_timestamp = parts[0][2:]
    if not _TIMESTAMP.fullmatch(raw_timestamp):
        raise InvalidSignature("Invalid webhook signature")
    signatures = []
    seen = set()
    for part in parts[1:]:
        if not part.startswith("v1=") or part.count(":") != 1:
            raise InvalidSignature("Invalid webhook signature")
        key_id, digest = part[3:].split(":")
        if (
            not _KEY_ID.fullmatch(key_id)
            or not _DIGEST.fullmatch(digest)
            or key_id in seen
        ):
            raise InvalidSignature("Invalid webhook signature")
        seen.add(key_id)
        signatures.append((key_id, digest))
    return int(raw_timestamp), signatures


def verify_payload(
    body: bytes,
    header: str,
    keys: tuple[SigningKey, ...],
    *,
    now: int | None = None,
    max_age_seconds: int = 300,
    future_skew_seconds: int = 30,
) -> VerifiedSignature:
    """Authenticate bytes and freshness; callers separately deduplicate event IDs."""
    _keys(keys)
    now = int(time.time()) if now is None else now
    _timestamp(now)
    if (
        type(max_age_seconds) is not int
        or not 1 <= max_age_seconds <= 86_400
        or type(future_skew_seconds) is not int
        or not 0 <= future_skew_seconds <= 300
    ):
        raise ValueError("Invalid signature freshness policy")
    if not isinstance(body, bytes) or len(body) > MAX_PAYLOAD_BYTES:
        raise InvalidSignature("Invalid webhook signature")
    timestamp, signatures = _parse_header(header)
    if timestamp < now - max_age_seconds or timestamp > now + future_skew_seconds:
        raise InvalidSignature("Invalid webhook signature")
    matched = None
    # Complete the bounded comparison loop, even if an earlier key matches.
    for key in keys:
        expected = _mac(body, timestamp, key)
        for key_id, actual in signatures:
            equal = hmac.compare_digest(expected, actual)
            if equal and key_id == key.key_id and matched is None:
                matched = key.key_id
    if matched is None:
        raise InvalidSignature("Invalid webhook signature")
    return VerifiedSignature(matched, timestamp)
