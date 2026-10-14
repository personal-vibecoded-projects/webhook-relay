# Declarative routing and dry runs

`compile_routes` accepts strict version-1 JSON and returns an immutable route
plan. `route_event` evaluates that plan against exact payload bytes and returns
delivery intents plus an execution trace. This PR does not connect to HTTP,
the database, or destination URLs. A future authenticated service must resolve
destination IDs in the authorized workspace and persist accepted plans/intents.

Example configuration:

```json
{
  "version": 1,
  "rules": [
    {
      "id": "large-invoices",
      "destination_id": "00000000-0000-4000-8000-000000000001",
      "priority": 100,
      "event_types": ["invoice.*"],
      "when": {
        "all": [
          {"path": "/amount", "op": "gte", "value": 10000},
          {"path": "/currency", "op": "in", "value": ["usd", "eur"]}
        ]
      },
      "projection": [
        {"source": "/id", "target": "invoice_id"},
        {"source": "/customer/id", "target": "customer_id", "required": false}
      ]
    }
  ]
}
```

Rules run by descending priority, then ascending rule ID. IDs must be unique.
Event patterns are exact types, `*`, or terminal namespace wildcards such as
`invoice.*` (matches descendants, not bare `invoice`). Enabled defaults to
true; priority defaults to zero. Multiple matching rules fan out to distinct
destination IDs. The first successful rule for a destination wins. `stop`
defaults to false and stops processing only when that rule adds a delivery;
a disabled, nonmatching, incomplete, or duplicate-destination rule cannot stop.

Predicates support nested `all`, `any`, and `not`, plus `eq`, `neq`, `in`,
`exists`, `prefix`, `gt`, `gte`, `lt`, and `lte`. Boolean groups are nonempty.
Leaf values are bounded scalars. JSON numbers compare numerically, so 1 equals
1.0; booleans are distinct from numbers. Ordered comparisons require numbers.
Missing fields fail every leaf except `exists: false`; null is present.
Negation negates the child result, so `not(eq)` can match a missing field.
Use an explicit existence check when that behavior is unwanted.

Paths use RFC 6901 escapes (`~0` for tilde, `~1` for slash), including empty
object keys and the empty root pointer. Arrays require canonical nonnegative
indices; leading zeros and `-` are missing. Projections copy selected values
to unique named top-level output fields. Missing required fields skip the
rule, optional missing fields are omitted, and explicit null is retained.
No projection means a copy of the complete payload. Delivery payloads do not
share mutable values with each other.

Limits: 64 rules, 512 predicate nodes globally, predicate depth 8, 16 children
per boolean group, 16 event patterns per rule, 32 membership values, 32
projection fields, 16 pointer segments, and 256-character pointer/value
strings. Configuration is capped at 128 KiB; event bodies at 256 KiB. JSON
also has a 32-depth/10,000-node budget, rejects duplicate keys, non-finite
numbers, invalid UTF-8, and unpaired surrogates. Configuration rejects unknown
fields and unsupported versions/operators rather than silently ignoring them.

Dry-run traces contain rule IDs and outcomes only: `disabled`,
`event_type_mismatch`, `predicate_mismatch`, `required_projection_missing`,
`duplicate_destination`, or `routed`. Stopped rules are not evaluated or traced.
Literal filter values and payloads are omitted from dataclass representations.
There is no expression evaluation, user regex, or external I/O in the engine.
