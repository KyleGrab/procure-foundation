# ADR-007: JWT carries one active_org_id, not the full membership list

**Status:** Accepted

**Context:** Spec section 4.6 requires consultants to belong to multiple client organisations. A token that
embeds every org+role a user has is a large attack surface: any endpoint that trusts role-from-token without
re-checking org context is a potential cross-tenant leak, and it's the kind of subtle bug that's easy to
introduce months later without noticing.

**Decision:** JWT claims are `sub, active_org_id, role, iat, exp` only. Organisation switching is an
explicit `POST /auth/switch-org` call that validates the target membership is active and issues a new,
narrowly-scoped token. The RLS session variable (ADR-003) is set from `active_org_id` on every request.

**Consequences:** One extra round-trip when a consultant switches client context, in exchange for every
token in the system being provably scoped to exactly one organisation at a time, and every org-switch being
an explicit, audited event rather than implicit client-side state.
