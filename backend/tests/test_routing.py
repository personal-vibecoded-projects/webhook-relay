import json
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from relay.routing import (
    MAX_CONFIG_BYTES,
    MAX_EVENT_BYTES,
    InvalidRoutingConfig,
    InvalidRoutingEvent,
    compile_routes,
    route_event,
)

DESTINATION = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"


def rule(**changes):
    value = {
        "id": "billing",
        "destination_id": DESTINATION,
        "event_types": ["invoice.*"],
    }
    value.update(changes)
    return value


def plan(*rules):
    return compile_routes(json.dumps({"version": 1, "rules": list(rules)}).encode())


def route(rules, payload=None, event_type="invoice.paid"):
    return route_event(plan(*rules), event_type, json.dumps(payload or {}).encode())


def leaf(op, value, path="/amount"):
    return {"path": path, "op": op, "value": value}


def test_empty_plan_and_whole_payload_routing():
    assert route([]).deliveries == ()
    result = route([rule()], {"id": "evt1", "items": [1, None]})
    assert result.deliveries[0].destination_id == UUID(DESTINATION)
    assert result.deliveries[0].payload == {"id": "evt1", "items": [1, None]}
    assert [(entry.rule_id, entry.outcome) for entry in result.trace] == [
        ("billing", "routed")
    ]


@pytest.mark.parametrize(
    ("patterns", "event_type", "matched"),
    [
        (["*"], "order.created", True),
        (["invoice.paid"], "invoice.paid", True),
        (["invoice.paid"], "invoice.void", False),
        (["invoice.*"], "invoice.paid", True),
        (["invoice.*"], "invoice.item.paid", True),
        (["invoice.*"], "invoice", False),
        (["invoice.*"], "invoices.paid", False),
        (["order.created", "invoice.paid"], "invoice.paid", True),
    ],
)
def test_event_pattern_boundaries(patterns, event_type, matched):
    assert (
        bool(route([rule(event_types=patterns)], event_type=event_type).deliveries)
        is matched
    )


@pytest.mark.parametrize(
    ("op", "expected", "actual", "matched"),
    [
        ("eq", 10, 10, True),
        ("eq", 10, 10.0, True),
        ("eq", 1, True, False),
        ("eq", None, None, True),
        ("eq", "10", 10, False),
        ("neq", 10, 9, True),
        ("neq", False, 0, True),
        ("in", [1, "yes", None], "yes", True),
        ("in", [1], True, False),
        ("prefix", "cus_", "cus_123", True),
        ("prefix", "cus_", 123, False),
        ("gt", 10, 11, True),
        ("gt", 10, 10, False),
        ("gte", 10, 10, True),
        ("lt", 10, 9, True),
        ("lte", 10, 10, True),
        ("gte", 0, True, False),
        ("gt", 1, "2", False),
        ("exists", True, None, True),
        ("exists", False, None, False),
    ],
)
def test_scalar_operators_and_json_types(op, expected, actual, matched):
    result = route([rule(when=leaf(op, expected))], {"amount": actual})
    assert bool(result.deliveries) is matched


@pytest.mark.parametrize(
    ("op", "expected", "matched"),
    [
        ("eq", None, False),
        ("neq", None, False),
        ("in", [None], False),
        ("exists", True, False),
        ("exists", False, True),
    ],
)
def test_missing_is_distinct_from_null(op, expected, matched):
    assert bool(route([rule(when=leaf(op, expected))]).deliveries) is matched


def test_nested_boolean_logic():
    predicate = {
        "all": [
            leaf("gte", 100),
            {"any": [leaf("eq", "usd", "/currency"), leaf("eq", "eur", "/currency")]},
            {"not": leaf("eq", True, "/refunded")},
        ]
    }
    for payload, matched in [
        ({"amount": 100, "currency": "usd", "refunded": False}, True),
        ({"amount": 100, "currency": "eur"}, True),
        ({"amount": 99, "currency": "usd"}, False),
        ({"amount": 100, "currency": "cad"}, False),
        ({"amount": 100, "currency": "usd", "refunded": True}, False),
    ]:
        assert bool(route([rule(when=predicate)], payload).deliveries) is matched


def test_json_pointer_escapes_and_array_indices():
    payload = {"a/b": {"~key": [{"": 7}]}, "01": 9}
    for pointer, expected in [("/a~1b/~0key/0/", 7), ("/01", 9)]:
        assert route([rule(when=leaf("eq", expected, pointer))], payload).deliveries
    for pointer in ["/a~1b/~0key/01/", "/a~1b/~0key/-/", "/a~1b/~0key/9999999999"]:
        assert not route([rule(when=leaf("exists", True, pointer))], payload).deliveries


def test_projection_preserves_null_omits_optional_and_skips_missing_required():
    projection = [
        {"source": "/id", "target": "external_id"},
        {"source": "/optional", "target": "optional", "required": False},
        {"source": "/null", "target": "null_value"},
    ]
    result = route([rule(projection=projection)], {"id": 7, "null": None})
    assert result.deliveries[0].payload == {"external_id": 7, "null_value": None}
    missing = route([rule(projection=projection)], {"null": None})
    assert missing.deliveries == ()
    assert missing.trace[0].outcome == "required_projection_missing"


def test_root_projection_and_delivery_payloads_do_not_share_mutable_values():
    rules = [
        rule(id="a", projection=[{"source": "", "target": "event"}]),
        rule(id="b", destination_id=OTHER),
    ]
    result = route(rules, {"items": [{"amount": 1}]})
    result.deliveries[0].payload["event"]["items"][0]["amount"] = 99
    assert result.deliveries[1].payload["items"][0]["amount"] == 1


def test_priority_sort_tie_break_and_destination_deduplication():
    result = route(
        [
            rule(id="z", priority=10),
            rule(id="a", priority=10),
            rule(id="first", destination_id=OTHER, priority=20),
        ]
    )
    assert [item.rule_id for item in result.deliveries] == ["first", "a"]
    assert [(item.rule_id, item.outcome) for item in result.trace] == [
        ("first", "routed"),
        ("a", "routed"),
        ("z", "duplicate_destination"),
    ]


def test_stop_applies_only_to_successfully_routed_rules():
    for first in [
        rule(id="a", enabled=False, stop=True),
        rule(id="a", event_types=["order.*"], stop=True),
        rule(id="a", when=leaf("eq", 999), stop=True),
        rule(id="a", projection=[{"source": "/missing", "target": "x"}], stop=True),
    ]:
        result = route([first, rule(id="b", destination_id=OTHER)])
        assert [item.rule_id for item in result.deliveries] == ["b"]
    stopped = route([rule(id="a", stop=True), rule(id="b", destination_id=OTHER)])
    assert len(stopped.deliveries) == len(stopped.trace) == 1


def test_duplicate_destination_with_stop_does_not_stop_other_routes():
    result = route(
        [rule(id="a"), rule(id="b", stop=True), rule(id="c", destination_id=OTHER)]
    )
    assert [item.rule_id for item in result.deliveries] == ["a", "c"]


def test_compiled_plan_is_immutable_and_trace_omits_values():
    compiled = plan(rule(when=leaf("eq", "customer-private", "/customer")))
    with pytest.raises(FrozenInstanceError):
        compiled.rules[0].priority = 100
    result = route_event(compiled, "invoice.paid", b'{"customer":"customer-private"}')
    assert "customer-private" not in repr(compiled)
    assert "customer-private" not in repr(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "Bad"},
        {"id": ""},
        {"destination_id": "https://example.com"},
        {"destination_id": None},
        {"destination_id": "00000000-0000-0000-0000-000000000000"},
        {"priority": True},
        {"priority": -1},
        {"priority": 1001},
        {"enabled": 1},
        {"stop": "yes"},
        {"unexpected": True},
        {"event_types": []},
        {"event_types": ["a.*.b"]},
        {"event_types": ["a", "a"]},
        {"event_types": ["a*"]},
        {"event_types": ["A"]},
        {"event_types": ["a" * 129]},
        {"when": None},
        {"projection": []},
    ],
)
def test_invalid_rule_configuration(changes):
    with pytest.raises(InvalidRoutingConfig):
        plan(rule(**changes))


@pytest.mark.parametrize(
    "predicate",
    [
        {"all": []},
        {"any": []},
        {"not": []},
        {"all": [leaf("eq", 1)] * 17},
        leaf("regex", ".*"),
        leaf("eq", {}),
        leaf("eq", "x" * 257),
        leaf("exists", 1),
        leaf("prefix", ""),
        leaf("gt", True),
        leaf("in", []),
        leaf("in", [1] * 33),
        leaf("in", [{}]),
        leaf("eq", 1, "no-slash"),
        leaf("eq", 1, "/bad~2"),
        leaf("eq", 1, "/bad~"),
        leaf("eq", 1, "/" + "/".join(["a"] * 17)),
        {"path": "/a", "op": "eq"},
    ],
)
def test_invalid_predicate_configuration(predicate):
    with pytest.raises(InvalidRoutingConfig):
        plan(rule(when=predicate))


@pytest.mark.parametrize(
    "projection",
    [
        [{"source": "/a", "target": "x"}] * 2,
        [{"source": "/a", "target": "../x"}],
        [{"source": "/a", "target": "x", "required": "yes"}],
        [{"source": "bad", "target": "x"}],
        [{"source": "/a", "target": "x", "extra": 1}],
        [{"source": "/a", "target": "x"}] * 33,
    ],
)
def test_invalid_projection_configuration(projection):
    with pytest.raises(InvalidRoutingConfig):
        plan(rule(projection=projection))


def test_rejects_duplicate_rules_and_complexity_budget():
    with pytest.raises(InvalidRoutingConfig):
        plan(rule(), rule())
    with pytest.raises(InvalidRoutingConfig):
        plan(*(rule(id=f"rule{i}") for i in range(65)))
    nested = leaf("eq", 1)
    for _ in range(9):
        nested = {"not": nested}
    with pytest.raises(InvalidRoutingConfig):
        plan(rule(when=nested))
    # 49 predicates per rule, so eleven rules exceed the global 512-node budget.
    wide = {"all": [{"any": [leaf("eq", 1), leaf("eq", 2)]} for _ in range(16)]}
    with pytest.raises(InvalidRoutingConfig):
        plan(*(rule(id=f"rule{i}", when=wide) for i in range(11)))


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"[]",
        b'{"version":true,"rules":[]}',
        b'{"version":2,"rules":[]}',
        b'{"version":1,"rules":[],"extra":1}',
        b'{"version":1,"version":1,"rules":[]}',
        b"\xff",
        b'{"version":1,"rules":NaN}',
        b"x" * (MAX_CONFIG_BYTES + 1),
    ],
)
def test_rejects_malformed_config_documents(body):
    with pytest.raises(InvalidRoutingConfig):
        compile_routes(body)


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b"x" * (MAX_EVENT_BYTES + 1),
    ],
)
def test_rejects_malformed_event_documents(body):
    with pytest.raises(InvalidRoutingEvent):
        route_event(plan(rule()), "invoice.paid", body)


def test_event_structure_budget_and_invalid_event_type():
    for payload in [{"items": [0] * 10001}, {"deep": [[[[0]]]]}]:
        if "deep" in payload:
            for _ in range(33):
                payload = {"deeper": payload}
        with pytest.raises(InvalidRoutingEvent):
            route_event(plan(rule()), "invoice.paid", json.dumps(payload).encode())
    with pytest.raises(InvalidRoutingEvent):
        route_event(plan(rule()), "Invoice.Paid", b"{}")


def test_maximum_rules_route_deterministically_without_side_effects():
    rules = [
        rule(
            id=f"rule{i:02}",
            destination_id=str(UUID(int=i + 1)),
            event_types=["*"],
            priority=i,
        )
        for i in range(64)
    ]
    compiled = plan(*rules)
    one = route_event(compiled, "invoice.paid", b'{"items":[1,2]}')
    two = route_event(compiled, "invoice.paid", b'{"items":[1,2]}')
    assert one == two
    assert len(one.deliveries) == 64
    assert one.deliveries[0].rule_id == "rule63"
