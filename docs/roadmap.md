# Review sequence

Do not begin an increment until the previous PR is merged. Database changes get
their own reviews. Each increment includes focused tests and a demo walkthrough.

1. Baseline: API health, dashboard shell, local runtime, CI, browser tests.
2. Database foundation: PostgreSQL, SQLAlchemy, Alembic, first workspace table,
   upgrade/downgrade tests. No public workspace access without authentication.
3. Membership: users, workspace roles, authenticated access and isolation tests.
4. Subscriptions: workspace-owned endpoints and filters; destination validation
   before enabling outbound network requests.
5. Ingestion: immutable events, idempotency keys, atomic persistence.
6. Delivery: queue state, worker leases, attempt history, concurrency.
7. Retries and signing: bounded backoff, timeouts, destination safeguards,
   signatures and secret handling.
8. Replay and history: authorized replay, pagination, dashboard integration.
9. Analytics and retention: delivery metrics and bounded cleanup.

Record actual CodeRabbit findings after review. Keep main working.
