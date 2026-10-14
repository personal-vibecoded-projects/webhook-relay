# Relay signature protocol v1

This PR supplies signing and verification primitives without adding an HTTP
endpoint or storing secrets. Integrate only after workspace authentication.

The header is `t=<unix-seconds>,v1=<key-id>:<lowercase-sha256-hex>`; during
rotation it may contain up to eight distinct `v1` entries. Each HMAC-SHA256
authenticates the exact bytes `v1.<timestamp>.<key-id>.` followed by the raw
request body. Key IDs are public identifiers; key material is 32–128 bytes
and must come from a secret manager. Preserve wire bytes before JSON parsing.

The receiver accepts any trusted active key. Default freshness is at most
300 seconds old with 30 seconds of future clock skew. Boundary values are
inclusive. Unknown versions, duplicate IDs, non-ASCII headers, and bodies
above 256 KiB fail closed. Verification uses constant-time digest comparison
and reports a generic failure without request data.

For rotation, first install the new verifier key, then sign with both keys,
then stop signing with the old key, and remove it after the freshness window.
Timestamps limit replay duration but do not provide exactly-once processing:
the intake service must deduplicate provider event identifiers per workspace.
Require TLS in deployment. This is Relay's own versioned protocol, rather
than a parser for provider-specific signature formats.
