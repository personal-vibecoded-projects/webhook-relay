import pytest

from relay.inbox import InvalidEvent, _snapshot


def test_snapshot_is_detached_and_key_order_is_irrelevant():
    payload = {"z": [1, 2], "a": {"nested": True}}
    stored, digest = _snapshot("invoice.paid", "evt1", payload)
    _, reordered = _snapshot(
        "invoice.paid", "evt1", {"a": {"nested": True}, "z": [1, 2]}
    )
    assert digest == reordered
    payload["z"].append(3)
    assert stored["z"] == [1, 2]
    assert _snapshot("invoice.void", "evt1", stored)[1] != digest


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {1: "value"},
        {"v": (1, 2)},
        {"v": float("nan")},
        {"v": float("inf")},
        {"v": object()},
        {"v": "\x00"},
        {"\x00": 1},
        {"v": "\ud800"},
        {"v": "x" * 131072},
    ],
)
def test_rejects_values_that_cannot_be_stored(payload):
    with pytest.raises(InvalidEvent):
        _snapshot("invoice.paid", "evt1", payload)


def test_accepts_literal_escaped_unicode_text():
    stored, _ = _snapshot("invoice.paid", "evt1", {"v": "\\u0000"})
    assert stored["v"] == "\\u0000"


def test_rejects_cycles_and_excessive_nodes():
    cycle = {}
    cycle["self"] = cycle
    for payload in [cycle, {"many": [0] * 10001}]:
        with pytest.raises(InvalidEvent):
            _snapshot("invoice.paid", "evt1", payload)
