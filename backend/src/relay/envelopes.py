"""Bounded JSON ingestion, ready for a future authenticated intake endpoint."""

import json
import re
from dataclasses import dataclass
from typing import Any

MAX_BODY_BYTES = 256 * 1024
MAX_DEPTH = 32
MAX_NODES = 10_000
_EVENT_TYPE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+){0,15}\Z")
_SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class InvalidEnvelope(ValueError):
    """Safe to expose: messages never include request content."""


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    source_id: str
    payload: dict[str, Any]


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidEnvelope("Duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _constant(_value):
    raise InvalidEnvelope("Non-finite numbers are not allowed")


def _validate_tree(root):
    stack = [(root, 0)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise InvalidEnvelope("JSON structure exceeds limits")
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise InvalidEnvelope("Invalid Unicode in JSON") from None
        elif isinstance(value, float):
            import math

            if not math.isfinite(value):
                raise InvalidEnvelope("Non-finite numbers are not allowed")
        elif isinstance(value, dict):
            stack.extend((item, depth + 1) for pair in value.items() for item in pair)
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def parse_envelope(body: bytes) -> EventEnvelope:
    """Reject ambiguous JSON before any persistence or routing side effects."""
    if len(body) > MAX_BODY_BYTES:
        raise InvalidEnvelope("Request body exceeds limit")
    try:
        data = json.loads(
            body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise InvalidEnvelope("Invalid JSON envelope") from None
    _validate_tree(data)
    if not isinstance(data, dict) or set(data) != {
        "event_type",
        "source_id",
        "payload",
    }:
        raise InvalidEnvelope("Expected event_type, source_id, and payload")
    event_type, source_id, payload = (
        data["event_type"],
        data["source_id"],
        data["payload"],
    )
    if (
        not isinstance(event_type, str)
        or len(event_type) > 128
        or not _EVENT_TYPE.fullmatch(event_type)
    ):
        raise InvalidEnvelope("Invalid event type")
    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise InvalidEnvelope("Invalid source identifier")
    if not isinstance(payload, dict):
        raise InvalidEnvelope("Payload must be a JSON object")
    return EventEnvelope(event_type, source_id, payload)
