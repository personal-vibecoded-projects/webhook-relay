import json

import pytest

from relay.envelopes import MAX_BODY_BYTES, InvalidEnvelope, parse_envelope


def body(**changes):
    value = {"event_type": "invoice.paid", "source_id": "evt_123", "payload": {}}
    value.update(changes)
    return json.dumps(value).encode()


def test_preserves_nested_json_without_coercion():
    payload = {"amount": 42, "paid": True, "nested": [None, {"name": "é"}]}
    envelope = parse_envelope(body(payload=payload))
    assert envelope.event_type == "invoice.paid"
    assert envelope.source_id == "evt_123"
    assert envelope.payload == payload


@pytest.mark.parametrize(
    "changes",
    [
        {"event_type": "Invoice.Paid"},
        {"event_type": "invoice..paid"},
        {"event_type": "a" * 129},
        {"event_type": 1},
        {"source_id": ""},
        {"source_id": "a" * 129},
        {"source_id": "bad id"},
        {"source_id": None},
        {"payload": []},
        {"payload": None},
        {"extra": "reject"},
    ],
)
def test_rejects_invalid_fields(changes):
    with pytest.raises(InvalidEnvelope):
        parse_envelope(body(**changes))


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"{}",
        b"not json",
        b"\xff",
        b'{"event_type":"invoice.paid","source_id":"evt1",'
        b'"payload":{"duplicate":1,"duplicate":2}}',
        b'{"event_type":"invoice.paid","event_type":"invoice.void",'
        b'"source_id":"evt1","payload":{}}',
        b'{"event_type":"invoice.paid","source_id":"evt1","payload":{"n":NaN}}',
        b'{"event_type":"invoice.paid","source_id":"evt1","payload":{"n":Infinity}}',
        b'{"event_type":"invoice.paid","source_id":"evt1","payload":{"n":1e999}}',
        b'{"event_type":"invoice.paid","source_id":"evt1",'
        b'"payload":{"value":"\\ud800"}}',
    ],
)
def test_rejects_ambiguous_or_invalid_json(raw):
    with pytest.raises(InvalidEnvelope):
        parse_envelope(raw)


def test_enforces_byte_limit_before_decoding():
    with pytest.raises(InvalidEnvelope, match="body exceeds"):
        parse_envelope(b"x" * (MAX_BODY_BYTES + 1))


def test_limits_depth_and_total_nodes():
    nested = {}
    for _ in range(33):
        nested = {"child": nested}
    for payload in [nested, {"many": [0] * 10_001}]:
        with pytest.raises(InvalidEnvelope, match="structure exceeds"):
            parse_envelope(body(payload=payload))


def test_errors_do_not_echo_content():
    with pytest.raises(InvalidEnvelope) as error:
        parse_envelope(body(event_type="private customer value"))
    assert "private customer value" not in str(error.value)
