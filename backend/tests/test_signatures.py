import hashlib
import hmac
import secrets

import pytest

from relay.signatures import (
    MAX_PAYLOAD_BYTES,
    InvalidSignature,
    SigningKey,
    sign_payload,
    verify_payload,
)


@pytest.fixture
def keys():
    return (
        SigningKey("old", secrets.token_bytes(32)),
        SigningKey("new", secrets.token_bytes(32)),
    )


def test_independent_digest_matches_wire_protocol(keys):
    body = b'{"unicode":"\xc3\xa9","n":1}'
    digest = hmac.new(keys[0].secret, b"v1.1000.old." + body, hashlib.sha256)
    header = sign_payload(body, keys[:1], timestamp=1000)
    assert hmac.compare_digest(header, "t=1000,v1=old:" + digest.hexdigest())


def test_rotation_accepts_either_active_key(keys):
    header = sign_payload(b"{}", keys, timestamp=1000)
    for trusted in [keys[:1], keys[1:], keys]:
        verified = verify_payload(b"{}", header, trusted, now=1000)
        assert verified.key_id == trusted[0].key_id
        assert verified.timestamp == 1000


def test_removed_key_cannot_verify(keys):
    header = sign_payload(b"{}", keys[:1], timestamp=1000)
    with pytest.raises(InvalidSignature):
        verify_payload(b"{}", header, keys[1:], now=1000)


@pytest.mark.parametrize("body", [b'{"n":2}', b'{ "n":1}', b'{"n":1}\n'])
def test_tampering_or_reserialization_invalidates_signature(keys, body):
    header = sign_payload(b'{"n":1}', keys, timestamp=1000)
    with pytest.raises(InvalidSignature):
        verify_payload(body, header, keys, now=1000)


@pytest.mark.parametrize("now", [969, 1301])
def test_rejects_future_and_expired_signatures(keys, now):
    with pytest.raises(InvalidSignature):
        verify_payload(b"{}", sign_payload(b"{}", keys, timestamp=1000), keys, now=now)


@pytest.mark.parametrize("now", [970, 1000, 1300])
def test_freshness_boundaries_are_inclusive(keys, now):
    verify_payload(b"{}", sign_payload(b"{}", keys, timestamp=1000), keys, now=now)


@pytest.mark.parametrize(
    "header",
    [
        "",
        "t=1000",
        "t=+1000,v1=x:" + "0" * 64,
        "t=01000,v1=x:" + "0" * 64,
        "t=1000,v2=x:" + "0" * 64,
        "t=1000,v1=x:" + "G" * 64,
        "t=1000,v1=é:" + "0" * 64,
        "t=1000,v1=x:" + "0" * 64 + ",v1=x:" + "0" * 64,
        "t=1000,v1=x:" + "0" * 64 + ",t=1000",
        "x" * 2049,
    ],
)
def test_rejects_malformed_headers(keys, header):
    with pytest.raises(InvalidSignature):
        verify_payload(b"{}", header, keys, now=1000)


def test_timestamp_and_key_id_are_authenticated(keys):
    header = sign_payload(b"{}", keys[:1], timestamp=1000)
    for changed in [
        header.replace("1000", "1001", 1),
        header.replace("v1=old:", "v1=new:"),
    ]:
        with pytest.raises(InvalidSignature):
            verify_payload(b"{}", changed, keys, now=1000)


def test_key_material_is_excluded_from_representation(keys):
    assert repr(keys[0]) == "SigningKey(key_id='old')"


def test_payload_limit_and_policy_validation(keys):
    oversized = b"x" * (MAX_PAYLOAD_BYTES + 1)
    with pytest.raises(ValueError):
        sign_payload(oversized, keys, timestamp=1000)
    with pytest.raises(InvalidSignature):
        verify_payload(oversized, "invalid", keys, now=1000)
    for policy in [
        {"max_age_seconds": 0},
        {"future_skew_seconds": -1},
        {"max_age_seconds": True},
    ]:
        with pytest.raises(ValueError):
            verify_payload(b"{}", "invalid", keys, now=1000, **policy)


def test_rejects_duplicate_and_invalid_keys(keys):
    for keyring in [(), (keys[0], keys[0]), (keys[0],) * 9]:
        with pytest.raises(ValueError):
            sign_payload(b"{}", keyring, timestamp=1000)
    with pytest.raises(ValueError):
        SigningKey("bad:id", secrets.token_bytes(32))
    with pytest.raises(ValueError):
        SigningKey("short", secrets.token_bytes(31))
