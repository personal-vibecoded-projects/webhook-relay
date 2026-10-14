# Event envelope contract

`relay.envelopes.parse_envelope` validates raw UTF-8 JSON before an intake
service writes to storage. This PR adds the library only; endpoint integration
requires authenticated workspace access.

An envelope has exactly three fields: `event_type` (lowercase segments such as
`invoice.paid`, up to 128 characters), `source_id` (an ASCII provider identifier,
up to 128 characters), and `payload` (a JSON object). The source identifier is
intended as a workspace-scoped idempotency key.

Bodies are bounded at 256 KiB, 32 levels of nesting, and 10,000 nodes (including
object keys). Duplicate keys, invalid UTF-8, unpaired Unicode surrogates,
non-finite numbers, and unexpected fields are rejected. Errors omit input data.
Callers must also bound streaming request reads before collecting the body;
this parser's byte limit applies to the bytes it receives.
