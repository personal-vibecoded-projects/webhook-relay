"""Compile bounded declarative routes and evaluate them without network I/O."""

import copy
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

MAX_CONFIG_BYTES = 128 * 1024
MAX_EVENT_BYTES = 256 * 1024
MAX_RULES = 64
MAX_PREDICATES = 512
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_EVENT = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_MISSING = object()


class InvalidRoutingConfig(ValueError):
    """Messages deliberately exclude literal values from configuration."""


class InvalidRoutingEvent(ValueError):
    pass


@dataclass(frozen=True)
class Predicate:
    operator: str
    path: tuple[str, ...] = field(default=(), repr=False)
    value: Any = field(default=None, repr=False)
    children: tuple["Predicate", ...] = ()


@dataclass(frozen=True)
class Projection:
    source: tuple[str, ...] = field(repr=False)
    target: str
    required: bool


@dataclass(frozen=True)
class Rule:
    rule_id: str
    destination_id: UUID
    priority: int
    event_types: tuple[str, ...]
    enabled: bool
    stop: bool
    predicate: Predicate | None
    projection: tuple[Projection, ...] | None


@dataclass(frozen=True)
class RoutePlan:
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class DeliveryIntent:
    destination_id: UUID
    rule_id: str
    payload: dict = field(repr=False)


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    outcome: str


@dataclass(frozen=True)
class RoutingDecision:
    deliveries: tuple[DeliveryIntent, ...]
    trace: tuple[RuleTrace, ...]


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _finite(_value):
    raise ValueError("Non-finite number")


def _decode(body: bytes, limit: int, error_type):
    if not isinstance(body, bytes) or len(body) > limit:
        raise error_type("JSON body exceeds limit or has invalid type")
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_finite
        )
    except (UnicodeError, ValueError, RecursionError):
        raise error_type("Invalid JSON document") from None
    stack = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 10_000:
            raise error_type("JSON structure exceeds limits")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError:
                raise error_type("Invalid Unicode") from None
        elif isinstance(item, float) and not math.isfinite(item):
            raise error_type("Non-finite JSON number")
    return value


def _shape(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise InvalidRoutingConfig("Invalid configuration fields")


def _pointer(value) -> tuple[str, ...]:
    if not isinstance(value, str) or len(value) > 256:
        raise InvalidRoutingConfig("Invalid JSON pointer")
    if value == "":
        return ()
    if not value.startswith("/"):
        raise InvalidRoutingConfig("JSON pointers must start with a slash")
    raw = value[1:].split("/")
    if len(raw) > 16 or any(re.search(r"~(?![01])", part) for part in raw):
        raise InvalidRoutingConfig("Invalid JSON pointer escape or depth")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in raw)


def _scalar(value):
    if value is None or type(value) in (bool, int, float):
        return
    if isinstance(value, str) and len(value) <= 256:
        return
    raise InvalidRoutingConfig("Predicate values must be bounded JSON scalars")


def _compile_predicate(value, budget, depth=0) -> Predicate:
    budget[0] += 1
    if budget[0] > MAX_PREDICATES or depth > 8:
        raise InvalidRoutingConfig("Predicate complexity exceeds limits")
    if isinstance(value, dict) and len(value) == 1:
        operator = next(iter(value))
        if operator in ("all", "any"):
            children = value[operator]
            if not isinstance(children, list) or not 1 <= len(children) <= 16:
                raise InvalidRoutingConfig("Boolean groups require one to 16 children")
            return Predicate(
                operator,
                children=tuple(
                    _compile_predicate(child, budget, depth + 1) for child in children
                ),
            )
        if operator == "not":
            return Predicate(
                "not",
                children=(_compile_predicate(value[operator], budget, depth + 1),),
            )
    _shape(value, ("path", "op", "value"))
    path = _pointer(value["path"])
    operator = value["op"]
    expected = value["value"]
    if not isinstance(operator, str) or operator not in {
        "eq",
        "neq",
        "in",
        "exists",
        "prefix",
        "gt",
        "gte",
        "lt",
        "lte",
    }:
        raise InvalidRoutingConfig("Unsupported predicate operator")
    if operator == "in":
        if not isinstance(expected, list) or not 1 <= len(expected) <= 32:
            raise InvalidRoutingConfig("Membership requires one to 32 values")
        for item in expected:
            _scalar(item)
        expected = tuple(expected)
    else:
        _scalar(expected)
    if operator == "exists" and type(expected) is not bool:
        raise InvalidRoutingConfig("Exists requires a boolean")
    if operator == "prefix" and (not isinstance(expected, str) or not expected):
        raise InvalidRoutingConfig("Prefix requires a nonempty string")
    if operator in ("gt", "gte", "lt", "lte") and type(expected) not in (int, float):
        raise InvalidRoutingConfig("Ordered comparisons require a number")
    return Predicate(operator, path=path, value=expected)


def _patterns(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise InvalidRoutingConfig("Expected one to 16 event type patterns")
    for pattern in value:
        if not isinstance(pattern, str) or len(pattern) > 128:
            raise InvalidRoutingConfig("Invalid event type pattern")
        if pattern == "*":
            continue
        base = pattern[:-2] if pattern.endswith(".*") else pattern
        if not _EVENT.fullmatch(base):
            raise InvalidRoutingConfig("Invalid event type pattern")
    if len(set(value)) != len(value):
        raise InvalidRoutingConfig("Duplicate event type patterns")
    return tuple(value)


def _projection(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise InvalidRoutingConfig("Expected one to 32 projection fields")
    fields = []
    targets = set()
    for item in value:
        _shape(item, ("source", "target"), ("required",))
        target = item["target"]
        required = item.get("required", True)
        if (
            not isinstance(target, str)
            or not _ID.fullmatch(target)
            or target in targets
            or type(required) is not bool
        ):
            raise InvalidRoutingConfig("Invalid or duplicate projection target")
        targets.add(target)
        fields.append(Projection(_pointer(item["source"]), target, required))
    return tuple(fields)


def compile_routes(body: bytes) -> RoutePlan:
    """Snapshot and compile strict version-1 JSON; order by priority, then rule ID."""
    config = _decode(body, MAX_CONFIG_BYTES, InvalidRoutingConfig)
    _shape(config, ("version", "rules"))
    if type(config["version"]) is not int or config["version"] != 1:
        raise InvalidRoutingConfig("Unsupported routing configuration version")
    if not isinstance(config["rules"], list) or len(config["rules"]) > MAX_RULES:
        raise InvalidRoutingConfig("Routing configuration exceeds rule limit")
    rules = []
    ids = set()
    budget = [0]
    for item in config["rules"]:
        _shape(
            item,
            ("id", "destination_id", "event_types"),
            ("priority", "enabled", "stop", "when", "projection"),
        )
        rule_id = item["id"]
        if not isinstance(rule_id, str) or not _ID.fullmatch(rule_id) or rule_id in ids:
            raise InvalidRoutingConfig("Invalid or duplicate rule identifier")
        ids.add(rule_id)
        try:
            if not isinstance(item["destination_id"], str):
                raise ValueError
            destination = UUID(item["destination_id"])
            if destination.int == 0:
                raise ValueError
        except ValueError:
            raise InvalidRoutingConfig("Invalid destination identifier") from None
        priority = item.get("priority", 0)
        enabled, stop = item.get("enabled", True), item.get("stop", False)
        if (
            type(priority) is not int
            or not 0 <= priority <= 1000
            or type(enabled) is not bool
            or type(stop) is not bool
        ):
            raise InvalidRoutingConfig("Invalid rule priority or flags")
        predicate = _compile_predicate(item["when"], budget) if "when" in item else None
        projection = _projection(item["projection"]) if "projection" in item else None
        rules.append(
            Rule(
                rule_id,
                destination,
                priority,
                _patterns(item["event_types"]),
                enabled,
                stop,
                predicate,
                projection,
            )
        )
    return RoutePlan(
        tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.rule_id)))
    )


def _lookup(payload, path):
    current = payload
    for part in path:
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        elif isinstance(current, list):
            # RFC 6901 array indices: no sign, leading zero, or append token.
            if not re.fullmatch(r"0|[1-9][0-9]*", part) or len(part) > 9:
                return _MISSING
            index = int(part)
            current = current[index] if index < len(current) else _MISSING
        else:
            return _MISSING
    return current


def _equal(actual, expected):
    if type(actual) in (int, float) and type(expected) in (int, float):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _matches(predicate, payload):
    operator = predicate.operator
    if operator == "all":
        return all(_matches(child, payload) for child in predicate.children)
    if operator == "any":
        return any(_matches(child, payload) for child in predicate.children)
    if operator == "not":
        return not _matches(predicate.children[0], payload)
    actual = _lookup(payload, predicate.path)
    if operator == "exists":
        return (actual is not _MISSING) == predicate.value
    if actual is _MISSING:
        return False
    if operator == "eq":
        return _equal(actual, predicate.value)
    if operator == "neq":
        return not _equal(actual, predicate.value)
    if operator == "in":
        return any(_equal(actual, option) for option in predicate.value)
    if operator == "prefix":
        return isinstance(actual, str) and actual.startswith(predicate.value)
    if type(actual) not in (int, float):
        return False
    if operator == "gt":
        return actual > predicate.value
    if operator == "gte":
        return actual >= predicate.value
    if operator == "lt":
        return actual < predicate.value
    return actual <= predicate.value


def route_event(plan: RoutePlan, event_type: str, body: bytes) -> RoutingDecision:
    """Dry-run routing: no database changes, URL resolution, or HTTP requests."""
    if (
        not isinstance(event_type, str)
        or len(event_type) > 128
        or not _EVENT.fullmatch(event_type)
    ):
        raise InvalidRoutingEvent("Invalid event type")
    payload = _decode(body, MAX_EVENT_BYTES, InvalidRoutingEvent)
    if not isinstance(payload, dict):
        raise InvalidRoutingEvent("Event payload must be an object")
    deliveries, trace = [], []
    destinations = set()
    for rule in plan.rules:
        outcome = None
        if not rule.enabled:
            outcome = "disabled"
        elif not any(
            pattern == "*"
            or pattern == event_type
            or (pattern.endswith(".*") and event_type.startswith(pattern[:-1]))
            for pattern in rule.event_types
        ):
            outcome = "event_type_mismatch"
        elif rule.predicate is not None and not _matches(rule.predicate, payload):
            outcome = "predicate_mismatch"
        projected = {}
        if outcome is None and rule.projection is not None:
            for projection in rule.projection:
                value = _lookup(payload, projection.source)
                if value is _MISSING:
                    if projection.required:
                        outcome = "required_projection_missing"
                        break
                else:
                    projected[projection.target] = copy.deepcopy(value)
        if outcome is None and rule.destination_id in destinations:
            outcome = "duplicate_destination"
        if outcome is None:
            destinations.add(rule.destination_id)
            deliveries.append(
                DeliveryIntent(
                    rule.destination_id,
                    rule.rule_id,
                    projected
                    if rule.projection is not None
                    else copy.deepcopy(payload),
                )
            )
            outcome = "routed"
        trace.append(RuleTrace(rule.rule_id, outcome))
        if outcome == "routed" and rule.stop:
            break
    return RoutingDecision(tuple(deliveries), tuple(trace))
