# ADR-003: Postgres RLS as a mandatory second tenant-isolation layer

**Status:** Accepted (goes beyond spec's app-layer-only instruction)

**Context:** Spec section 7 requires app-layer tenant filtering and cross-tenant tests. That's necessary but
not sufficient: a single missed WHERE clause in a future code change is a real breach vector for a product
whose entire value is other companies' confidential pricing.

**Decision:** Every tenant-scoped table gets `ENABLE ROW LEVEL SECURITY` with a policy against
`current_setting('app.current_org_id')`, set once per request from the validated JWT's `active_org_id`
claim in the DB session dependency. App-layer filtering stays as the first line (clarity, query planning);
RLS is the layer that holds even when the first line fails.

**Consequences:** Slightly more DB setup (policies per table, migration discipline to add RLS to every new
tenant-scoped table — enforced via a migration lint check in Phase 1 CI), marginal per-query overhead
(predicate on an already-indexed column), in exchange for tenant isolation that doesn't rely entirely on
every future engineer remembering to filter correctly.
